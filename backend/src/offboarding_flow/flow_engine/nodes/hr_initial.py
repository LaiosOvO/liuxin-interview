"""hr_initial 节点：HR 初审 — 上级审批 advance 后的人工节点（Phase 2 Plan 02）。

三态决策（FLOW-04 / FLOW-05）：
- advance → fan-out 到 5 并行节点（device_return / access_revoke / ...）
- return → 回到 apply（要求重新提交材料）
- reject → 流程终止
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

HR_INITIAL_NODE_NAME = "hr_initial"
HR_INITIAL_NODE_TITLE = "HR 初审"
HR_INITIAL_NODE_DESCRIPTION = "请检查离职申请材料是否齐全，决定通过 / 退回补材料 / 拒绝。"

logger = logging.getLogger(__name__)


async def hr_initial_node(state: OffboardingState) -> dict:
    """HR 初审节点函数：interrupt 等三态决策。"""
    logger.info(
        "[hr_initial_node] flow_id=%s — interrupt for human decision",
        state.get("flow_id"),
    )

    decision = interrupt(
        {
            "node_name": HR_INITIAL_NODE_NAME,
            "node_title": HR_INITIAL_NODE_TITLE,
            "node_description": HR_INITIAL_NODE_DESCRIPTION,
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
                "node_name": HR_INITIAL_NODE_NAME,
                "node_title": HR_INITIAL_NODE_TITLE,
                "result_text": decision.get("result_text", ""),
                "actor": decision.get("actor", "unknown"),
                "completed_at": decision.get(
                    "completed_at",
                    datetime.now(UTC).isoformat(),
                ),
            }
        ],
    }
