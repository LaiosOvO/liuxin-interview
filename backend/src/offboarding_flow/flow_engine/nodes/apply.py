"""apply 节点：流程入口。

Phase 1: 仅初始化 state（写 employee_id / 初始 context）。
不 interrupt — 自动推进到 manager_review。

Phase 2 才完整接入 Repository 业务层；本 Plan 节点函数留 TODO。
业务表的双写实际由 service 层（Plan 06）在 API 入口预先 upsert，节点函数仅负责
state 推进。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from offboarding_flow.flow_engine.state import OffboardingState

APPLY_NODE_NAME = "apply"
APPLY_NODE_TITLE = "申请提交"

logger = logging.getLogger(__name__)


async def apply_node(state: OffboardingState) -> dict:
    """apply 节点函数：自动节点（无 interrupt），仅累计 node_results。"""
    logger.info(
        "[apply_node] flow_id=%s employee_id=%s",
        state.get("flow_id"),
        state.get("employee_id"),
    )
    # TODO(Plan 06 / Phase 2): 注入 NodeRepository 通过依赖反转，upsert apply 节点
    # 当前实现：仅在 state.node_results 追加 apply 完成记录（Annotated reducer 追加而非覆盖）
    return {
        "current_action": "advance",
        "node_results": [
            {
                "node_name": APPLY_NODE_NAME,
                "node_title": APPLY_NODE_TITLE,
                "result_text": "离职申请已提交",
                "actor": state.get("employee_id", "unknown"),
                "completed_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
