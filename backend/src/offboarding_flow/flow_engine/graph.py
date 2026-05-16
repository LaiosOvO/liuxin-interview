"""StateGraph 构建 + 全局单例（Phase 1）。

最小拓扑：START → apply → manager_review → END
Phase 2 才扩展到 10 节点 + 并行 fan-out/fan-in。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langgraph.graph import END, START, StateGraph

from .checkpointer import make_checkpointer
from .nodes import (
    APPLY_NODE_NAME,
    MANAGER_REVIEW_NODE_NAME,
    apply_node,
    manager_review_node,
)
from .state import OffboardingState

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_graph: Any | None = None


def _route_after_manager(state: OffboardingState) -> str:
    """manager_review 后的路由（Phase 1 简化版）。

    - reject → END（流程终止）
    - advance / return → END（Phase 1 manager_review 是最后节点，下一节点 hr_initial 在 Phase 2 加）
    """
    action = state.get("current_action")
    logger.info(
        "[route] after manager_review: action=%s → END (Phase 1 stops here)",
        action,
    )
    return END


def _build_state_graph() -> StateGraph:
    """构建未 compile 的 StateGraph。"""
    builder = StateGraph(OffboardingState)
    builder.add_node(APPLY_NODE_NAME, apply_node)
    builder.add_node(MANAGER_REVIEW_NODE_NAME, manager_review_node)

    builder.add_edge(START, APPLY_NODE_NAME)
    builder.add_edge(APPLY_NODE_NAME, MANAGER_REVIEW_NODE_NAME)
    builder.add_conditional_edges(
        MANAGER_REVIEW_NODE_NAME,
        _route_after_manager,
        {END: END},
    )

    return builder


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
    logger.info("[graph] built and compiled (saver=%s)", type(saver).__name__)
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
