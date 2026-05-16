"""applicant_final_confirm 节点（DF-02 ★★★★★）— PRD §4.5 申请人最终确认。

与其他人工节点的关键差异：
1. interrupt payload 含 "timeline" 字段（state.node_results 整段，前端 + Phase 4 邮件渲染）
2. interrupt payload 含 "glm_summary" 字段（Slice 4C LLM-02 — AI 摘要，失败为 None 走降级）
3. 仅 advance / return 两态决策，无 reject（PRD §4.5.2）
4. 默认 actor = state.employee_id（申请人本人）
5. 默认 result_text 视 action 而定（无异议已确认 / 有异议退回 HR 终审）

Slice 4C 改动:
- interrupt payload 加 glm_summary 字段
- LLM 调用失败 / 超时 / 空返回均不阻塞节点（PRD LLM-03 + PITFALLS #22）
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

APPLICANT_FINAL_CONFIRM_NODE_NAME = "applicant_final_confirm"
APPLICANT_FINAL_CONFIRM_NODE_TITLE = "申请人最终确认"
APPLICANT_FINAL_CONFIRM_NODE_DESCRIPTION = (
    "你的离职流程已完成全部审核环节，请最终确认以下执行记录无误。如有异议可退回 HR 终审复核。"
)

logger = logging.getLogger(__name__)


async def _safe_glm_summary(timeline: list[Any]) -> str | None:
    """对 timeline 跑 LLM 摘要，任何错都吞掉（节点函数必须幂等且不阻塞）。

    分离成独立函数方便测试 patch + 保持节点主体短小。
    timeline 真实类型是 list[NodeResult]（TypedDict），applicant_summary 用 .get(...)
    所以兼容；这里用 list[Any] 避免循环 import。
    """
    try:
        from offboarding_flow.services.applicant_summary_service import applicant_summary

        return await applicant_summary(timeline)
    except Exception as e:
        logger.warning(
            "[applicant_final_confirm] glm_summary 调用失败（已降级）: %s",
            type(e).__name__,
        )
        return None


async def applicant_final_confirm_node(state: OffboardingState) -> dict[str, Any]:
    """申请人最终确认节点 — 聚合 timeline + AI 摘要并 interrupt 等申请人决策。"""
    timeline = list(state.get("node_results") or [])
    logger.info(
        "[applicant_final_confirm] flow=%s timeline_len=%d",
        state.get("flow_id"),
        len(timeline),
    )

    # Slice 4C LLM-02: AI 摘要（失败为 None 走降级）
    glm_summary = await _safe_glm_summary(timeline)

    decision = interrupt(
        {
            "node_name": APPLICANT_FINAL_CONFIRM_NODE_NAME,
            "node_title": APPLICANT_FINAL_CONFIRM_NODE_TITLE,
            "node_description": APPLICANT_FINAL_CONFIRM_NODE_DESCRIPTION,
            "flow_id": state.get("flow_id"),
            "employee_id": state.get("employee_id"),
            "timeline": timeline,  # 前端 + Phase 4 邮件都用这段
            "glm_summary": glm_summary,  # Slice 4C — None 时调用方走规则模板降级
        }
    )

    if not isinstance(decision, dict):
        decision = {"action": "advance", "result_text": str(decision), "actor": "unknown"}

    # 申请人节点无 reject — 任何非 return 都视为 advance（防御性）
    action = decision.get("action", "advance")
    if action not in ("advance", "return"):
        logger.warning(
            "[applicant_final_confirm] flow=%s 收到非法 action=%s，回退为 advance",
            state.get("flow_id"),
            action,
        )
        action = "advance"

    # 默认 actor = 申请人 username
    actor = decision.get("actor") or state.get("employee_id", "unknown")

    # 默认 result_text 视 action 而定
    default_text = "无异议，已确认" if action == "advance" else "有异议，退回 HR 终审"

    return {
        "current_action": action,
        "node_results": [
            {
                "node_name": APPLICANT_FINAL_CONFIRM_NODE_NAME,
                "node_title": APPLICANT_FINAL_CONFIRM_NODE_TITLE,
                "result_text": decision.get("result_text") or default_text,
                "actor": actor,
                "completed_at": decision.get(
                    "completed_at",
                    datetime.now(UTC).isoformat(),
                ),
            }
        ],
    }
