"""hr_final 节点：HR 终审 — 5 并行 fan-in 之后的人工节点（Phase 2 Plan 02）。

三态决策（FLOW-04 / FLOW-05）：
- advance → applicant_final_confirm（申请人最终确认）
- return → device_return（v1 简化：退回到第一个并行节点，HR 可重做整段并行）
- reject → 流程终止
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

HR_FINAL_NODE_NAME = "hr_final"
HR_FINAL_NODE_TITLE = "HR 终审"
HR_FINAL_NODE_DESCRIPTION = (
    "请最终审核所有并行环节（设备 / 权限 / 知识 / 财务 / 法务）的执行结果，"
    "决定通过 / 退回（重做某并行节点）/ 拒绝。"
)

logger = logging.getLogger(__name__)


async def hr_final_node(state: OffboardingState) -> dict:
    """HR 终审节点函数：interrupt 等三态决策。"""
    logger.info(
        "[hr_final_node] flow_id=%s — interrupt for human decision",
        state.get("flow_id"),
    )

    decision = interrupt(
        {
            "node_name": HR_FINAL_NODE_NAME,
            "node_title": HR_FINAL_NODE_TITLE,
            "node_description": HR_FINAL_NODE_DESCRIPTION,
            "flow_id": state.get("flow_id"),
            "employee_id": state.get("employee_id"),
        }
    )

    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}

    return {
        "current_action": decision["action"],
        "node_results": [
            {
                "node_name": HR_FINAL_NODE_NAME,
                "node_title": HR_FINAL_NODE_TITLE,
                "result_text": decision.get("result_text", ""),
                "actor": decision.get("actor", "unknown"),
                "completed_at": decision.get(
                    "completed_at",
                    datetime.now(UTC).isoformat(),
                ),
            }
        ],
    }
