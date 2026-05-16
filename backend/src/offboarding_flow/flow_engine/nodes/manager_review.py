"""manager_review 节点：上级审批 — Phase 1 唯一的 interrupt 节点。

关键设计（CONTEXT §4 + SUMMARY R3 + PITFALLS #16）：
- dynamic interrupt() + Command(resume=...) 模式（不用 interrupt_before）
- 节点函数必须幂等：interrupt 抛 GraphInterrupt 后会重跑整个节点函数
- Phase 1 节点函数不调用 Repository — Plan 06 在 API 层（service）做业务表的 upsert
- Phase 2 才把节点函数完整接入 Repository（通过 context 或 contextvars 注入 session）
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

MANAGER_REVIEW_NODE_NAME = "manager_review"
MANAGER_REVIEW_NODE_TITLE = "上级审批"

logger = logging.getLogger(__name__)


async def manager_review_node(state: OffboardingState) -> dict:
    """manager_review 节点：interrupt 等三态决策。"""
    logger.info(
        "[manager_review_node] flow_id=%s — interrupt for human decision",
        state.get("flow_id"),
    )

    # dynamic interrupt — 抛 GraphInterrupt 后节点函数会重跑（PITFALLS #16）
    # Plan 06 在 API 层 graph.ainvoke(Command(resume={action, result_text, actor})) 唤醒
    decision = interrupt(
        {
            "node_name": MANAGER_REVIEW_NODE_NAME,
            "node_title": MANAGER_REVIEW_NODE_TITLE,
            "node_description": "请审批此离职申请并填写意见",
            "flow_id": state.get("flow_id"),
            "employee_id": state.get("employee_id"),
        }
    )

    logger.info(
        "[manager_review_node] resumed with action=%s actor=%s",
        decision.get("action") if isinstance(decision, dict) else decision,
        decision.get("actor") if isinstance(decision, dict) else None,
    )

    # 当 LangGraph 多次中断时 Command(resume) 是 dict（直接传入）
    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}

    return {
        "current_action": decision["action"],
        "node_results": [
            {
                "node_name": MANAGER_REVIEW_NODE_NAME,
                "node_title": MANAGER_REVIEW_NODE_TITLE,
                "result_text": decision.get("result_text", ""),
                "actor": decision.get("actor", "unknown"),
                "completed_at": decision.get(
                    "completed_at",
                    datetime.now(UTC).isoformat(),
                ),
            }
        ],
    }
