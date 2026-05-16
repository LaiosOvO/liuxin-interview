"""test_archive_node.py — archive 自动节点单测（Phase 2 Plan 04）。"""

from __future__ import annotations

import inspect
from datetime import datetime

from offboarding_flow.flow_engine.nodes.archive import ARCHIVE_NODE_NAME, archive_node


async def test_archive_returns_advance_and_node_result():
    """archive 返回 current_action=advance + 含 archive 节点结果。"""
    result = await archive_node(
        {
            "flow_id": "x",
            "employee_id": "zhang.san",
            "current_action": None,
            "node_results": [],
            "context": {},
        }
    )
    assert result["current_action"] == "advance"
    assert len(result["node_results"]) == 1
    nr = result["node_results"][0]
    assert nr["node_name"] == ARCHIVE_NODE_NAME
    assert nr["actor"] == "system:archivist"


async def test_archive_completed_at_is_iso():
    """completed_at 应是合法 ISO 8601 含时区。"""
    result = await archive_node(
        {
            "flow_id": "x",
            "employee_id": "zhang.san",
            "current_action": None,
            "node_results": [],
            "context": {},
        }
    )
    dt = datetime.fromisoformat(result["node_results"][0]["completed_at"])
    assert dt.tzinfo is not None


def test_archive_is_async_function():
    """archive_node 应为 async function（LangGraph 节点契约）。"""
    assert inspect.iscoroutinefunction(archive_node)
