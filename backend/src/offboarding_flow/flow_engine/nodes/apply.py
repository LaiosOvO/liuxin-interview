"""apply 节点：申请人填写离职申请 — 人工 interrupt 节点。

设计修订（Bug 3 修复）：
原版是自动节点（写死 advance），导致申请人没机会填写申请就直接给上级发邮件。
现在改成 interrupt 节点：起流程后等申请人提交（advance）才推进到 manager_review。
manager_review 退回时也会回到 apply 让申请人修改后重新提交。

幂等：interrupt 抛 GraphInterrupt 后节点函数会重跑，本节点函数无副作用，安全。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

APPLY_NODE_NAME = "apply"
APPLY_NODE_TITLE = "提交离职申请"

logger = logging.getLogger(__name__)


async def apply_node(state: OffboardingState) -> dict:
    """apply 节点函数：interrupt 等申请人填写申请。"""
    logger.info(
        "[apply_node] flow_id=%s employee_id=%s — interrupt for applicant",
        state.get("flow_id"),
        state.get("employee_id"),
    )

    decision = interrupt(
        {
            "node_name": APPLY_NODE_NAME,
            "node_title": APPLY_NODE_TITLE,
            "node_description": "请填写离职理由 / 最后工作日 / 交接计划等申请信息",
            "flow_id": state.get("flow_id"),
            "employee_id": state.get("employee_id"),
        }
    )

    logger.info(
        "[apply_node] resumed with action=%s actor=%s",
        decision.get("action") if isinstance(decision, dict) else decision,
        decision.get("actor") if isinstance(decision, dict) else None,
    )

    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}

    return {
        "current_action": decision["action"],
        "node_results": [
            {
                "node_name": APPLY_NODE_NAME,
                "node_title": APPLY_NODE_TITLE,
                "result_text": decision.get("result_text", ""),
                "actor": decision.get("actor", "unknown"),
                "completed_at": decision.get(
                    "completed_at",
                    datetime.now(UTC).isoformat(),
                ),
            }
        ],
    }
