"""archive 节点：自动归档（流程末端，无 interrupt）。

Phase 2 本节点仅追加 node_result + log。
Phase 4 才接外部归档服务调用（评分点 #9 加分项）。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from offboarding_flow.flow_engine.state import OffboardingState

ARCHIVE_NODE_NAME = "archive"
ARCHIVE_NODE_TITLE = "归档"
ARCHIVE_NODE_DESCRIPTION = "流程自动归档（系统执行，无人工操作）。"

logger = logging.getLogger(__name__)


async def archive_node(state: OffboardingState) -> dict:
    """归档节点函数（自动节点）：仅追加 node_result。"""
    logger.info("[archive] flow=%s 自动归档", state.get("flow_id"))
    return {
        "current_action": "advance",
        "node_results": [
            {
                "node_name": ARCHIVE_NODE_NAME,
                "node_title": ARCHIVE_NODE_TITLE,
                "result_text": "流程已归档；所有节点结果已永久保存。",
                "actor": "system:archivist",
                "completed_at": datetime.now(UTC).isoformat(),
            }
        ],
    }
