"""人工节点工厂 — 把"interrupt + decision 解析 + node_results 追加"模板复用化。

生成的节点函数与 manager_review_node / hr_initial_node 行为一致。

Phase 2 Plan 03 用于 5 个并行节点（device_return / access_revoke / knowledge_handover /
finance_settle / legal_sign）— 这些节点结构完全相同，只是常量不同。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.types import interrupt

from offboarding_flow.flow_engine.state import OffboardingState

logger = logging.getLogger(__name__)


def make_human_node(
    node_name: str,
    node_title: str,
    node_description: str,
) -> Callable[[OffboardingState], Awaitable[dict[str, Any]]]:
    """生成一个标准的人工节点函数（interrupt + decision 解析 + node_results 追加）。

    Args:
        node_name: 节点名（snake_case，如 device_return）
        node_title: 显示标题（如 "设备归还"）
        node_description: 节点说明（前端展示给责任人）

    Returns:
        async 节点函数，可直接 add_node(name, fn) 注册到 StateGraph
    """

    async def _node(state: OffboardingState) -> dict[str, Any]:
        logger.info(
            "[%s] flow=%s interrupt for human decision",
            node_name,
            state.get("flow_id"),
        )
        decision = interrupt(
            {
                "node_name": node_name,
                "node_title": node_title,
                "node_description": node_description,
                "flow_id": state.get("flow_id"),
                "employee_id": state.get("employee_id"),
            }
        )
        if not isinstance(decision, dict):
            decision = {
                "action": "advance",
                "result_text": str(decision),
                "actor": "unknown",
            }
        return {
            "current_action": decision["action"],
            "node_results": [
                {
                    "node_name": node_name,
                    "node_title": node_title,
                    "result_text": decision.get("result_text", ""),
                    "actor": decision.get("actor", "unknown"),
                    "completed_at": decision.get(
                        "completed_at",
                        datetime.now(UTC).isoformat(),
                    ),
                }
            ],
        }

    _node.__name__ = f"{node_name}_node"
    return _node
