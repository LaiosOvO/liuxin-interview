"""StateGraph 构建 + 全局单例（Phase 2 Plan 05 + Phase 4.5 拓扑插入）。

完整拓扑（PRD §4.1 DAG + 02-CONTEXT §4 + PRD §18 加分项）：
    START → apply → manager_review ──reject→ END
                        ↓ advance
                    hr_initial ──return→ apply  ──reject→ END
                        ↓ advance（fan-out 5 并行节点）
                ┌────┬────┬────┬────┐
                ↓    ↓    ↓    ↓    ↓
        device_  access_  knowledge_  finance_  legal_
        return   revoke   handover    settle    sign
                └────┴────┴────┴────┘ (LangGraph 自动 fan-in)
                        ↓ all done
                    hr_final ──reject→ END ──return→ device_return (v1 简化)
                        ↓ advance
                applicant_final_confirm ──return→ hr_final
                        ↓ advance
                auto_archive_to_storage   ← Phase 4.5 新增（PRD §18，AutoNode 演示）
                        ↓ (失败 raise → 流程卡住等运维介入)
                    archive → END
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .checkpointer import make_checkpointer
from .nodes import (
    APPLICANT_FINAL_CONFIRM_NODE_NAME,
    APPLY_NODE_NAME,
    ARCHIVE_NODE_NAME,
    AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
    HR_FINAL_NODE_NAME,
    HR_INITIAL_NODE_NAME,
    MANAGER_REVIEW_NODE_NAME,
    PARALLEL_NODES_META,
    applicant_final_confirm_node,
    apply_node,
    archive_node,
    auto_archive_to_storage_node,
    hr_final_node,
    hr_initial_node,
    manager_review_node,
)
from .routes import (
    APPLY,
    HR_INITIAL,
    PARALLEL_NODES,
    route_after_applicant,
    route_after_hr_final,
    route_after_manager_review,
)
from .state import OffboardingState

logger = logging.getLogger(__name__)

_graph: Any | None = None


def _route_after_hr_initial_to_parallel(state: OffboardingState):
    """hr_initial 三态决策路由（advance 时 fan-out 5 并行节点）。

    LangGraph 1.x 条件边路由函数可返回 list[Send] 实现 dynamic fan-out。
    - reject → END
    - return → apply
    - advance → list[Send(name, state)] for 5 PARALLEL_NODES
    """
    action = state.get("current_action")
    logger.info("[route] after hr_initial action=%s", action)
    if action == "reject":
        return END
    if action == "return":
        return APPLY
    # advance → fan-out 全部 5 并行节点（每个 Send 把 state 复制给目标节点）
    return [Send(node, state) for node in PARALLEL_NODES]


def _build_state_graph() -> StateGraph:
    """构建未 compile 的 StateGraph（Phase 2 完整 10 节点版）。"""
    b: StateGraph = StateGraph(OffboardingState)

    # ---- 1. 注册全部 10 节点 ----
    b.add_node(APPLY_NODE_NAME, apply_node)
    b.add_node(MANAGER_REVIEW_NODE_NAME, manager_review_node)
    b.add_node(HR_INITIAL_NODE_NAME, hr_initial_node)
    for name, _title, _desc, fn in PARALLEL_NODES_META:
        b.add_node(name, fn)
    b.add_node(HR_FINAL_NODE_NAME, hr_final_node)
    b.add_node(APPLICANT_FINAL_CONFIRM_NODE_NAME, applicant_final_confirm_node)
    # Phase 4.5 加分项（PRD §18）：在 applicant 与 archive 之间插入 auto_archive_to_storage
    b.add_node(AUTO_ARCHIVE_TO_STORAGE_NODE_NAME, auto_archive_to_storage_node)
    b.add_node(ARCHIVE_NODE_NAME, archive_node)

    # ---- 2. 入口边 ----
    b.add_edge(START, APPLY_NODE_NAME)
    b.add_edge(APPLY_NODE_NAME, MANAGER_REVIEW_NODE_NAME)

    # ---- 3. manager_review 三态条件边 ----
    b.add_conditional_edges(
        MANAGER_REVIEW_NODE_NAME,
        route_after_manager_review,
        {END: END, HR_INITIAL: HR_INITIAL_NODE_NAME},
    )

    # ---- 4. hr_initial 三态条件边 + advance 时 fan-out 5 并行节点 ----
    # mapping 列表声明所有可能目标（END / APPLY / 5 并行节点）
    b.add_conditional_edges(
        HR_INITIAL_NODE_NAME,
        _route_after_hr_initial_to_parallel,
        [END, APPLY_NODE_NAME, *PARALLEL_NODES],
    )

    # ---- 5. 5 并行节点 fan-in → hr_final（LangGraph 自动等待所有源节点 done）----
    for name in PARALLEL_NODES:
        b.add_edge(name, HR_FINAL_NODE_NAME)

    # ---- 6. hr_final 三态条件边 ----
    # v1 简化：return → 第一个并行节点（重做 5 节点）
    b.add_conditional_edges(
        HR_FINAL_NODE_NAME,
        route_after_hr_final,
        {
            END: END,
            PARALLEL_NODES[0]: PARALLEL_NODES[0],
            APPLICANT_FINAL_CONFIRM_NODE_NAME: APPLICANT_FINAL_CONFIRM_NODE_NAME,
        },
    )

    # ---- 7. applicant_final_confirm 两态条件边（Phase 4.5：advance 改到 auto_archive_to_storage）----
    b.add_conditional_edges(
        APPLICANT_FINAL_CONFIRM_NODE_NAME,
        route_after_applicant,
        {
            HR_FINAL_NODE_NAME: HR_FINAL_NODE_NAME,
            AUTO_ARCHIVE_TO_STORAGE_NODE_NAME: AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
        },
    )

    # ---- 7.5 Phase 4.5：auto_archive_to_storage → archive（成功后直接进归档）----
    # 失败时节点函数 raise → graph.ainvoke 失败 → 流程卡住等运维介入（不自动绕过）
    b.add_edge(AUTO_ARCHIVE_TO_STORAGE_NODE_NAME, ARCHIVE_NODE_NAME)

    # ---- 8. archive → END ----
    b.add_edge(ARCHIVE_NODE_NAME, END)

    return b


async def build_graph(use_memory_saver: bool = False) -> Any:
    """构建并 compile graph。

    - production：用 AsyncPostgresSaver
    - 测试：use_memory_saver=True → 用 InMemorySaver
    """
    global _graph
    if _graph is not None:
        return _graph

    builder = _build_state_graph()

    if use_memory_saver:
        from langgraph.checkpoint.memory import InMemorySaver

        saver: Any = InMemorySaver()
    else:
        saver = await make_checkpointer()

    _graph = builder.compile(checkpointer=saver)
    logger.info(
        "[graph] built and compiled with 11 nodes (saver=%s) — Phase 4.5 含 auto_archive_to_storage",
        type(saver).__name__,
    )
    return _graph


def get_graph() -> Any:
    """返回已 build 的 graph；若未 build 抛错。"""
    if _graph is None:
        raise RuntimeError("graph not built yet — call build_graph() first")
    return _graph


async def dispose_graph() -> None:
    """清理 graph 单例（用于 shutdown / 测试 teardown）。"""
    global _graph
    _graph = None
