"""MCP read tools 单元测试（MCP-02）。

覆盖（CLAUDE.md §2.3 — 集成测试禁止 mock DB；这里用真 PG via db_session
fixture）：
1. list_flows 空 filter='all' → 返回当前 DB 中所有 flow
2. list_flows filter='active' 过滤 in_progress 状态
3. list_flows 错 filter 值 → ToolError
4. get_flow 不存在 → ToolError "未找到"
5. get_flow 存在 → 返回 flow + nodes + dag_markdown 非空
6. get_node_form 已知节点 → 返回 payload + assignee
7. get_user_assignments(li.si) → 返回该用户分配的所有节点
8. get_final_summary 有 node_results → 返回含 ai_disclaimer
9. get_handover_docs 流程含 ctx.handover_docs → 返回 list
10. get_meeting_summary meeting_id 空 → ToolError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.mcp import tools_read
from offboarding_flow.services.ai_disclaimer import AI_DISCLAIMER

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 辅助 — mock Context
# ---------------------------------------------------------------------------


def _make_ctx(sub: str = "test.user", role: str = "admin") -> MagicMock:
    """伪造 fastmcp.Context（get_state 是 async）。"""
    ctx = MagicMock()
    state = {"user_sub": sub, "user_role": role}

    async def _get_state(k: str):
        return state.get(k, "unknown")

    ctx.get_state = AsyncMock(side_effect=_get_state)
    return ctx


# ---------------------------------------------------------------------------
# 1-3: list_flows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_flows_returns_flows_filter_all(sample_node_and_user) -> None:
    """list_flows filter='all' → 至少含 sample_node_and_user 的 flow。"""
    ctx = _make_ctx()
    result = await tools_read.list_flows(filter="all", ctx=ctx)
    assert "flows" in result
    assert "total" in result
    assert result["total"] >= 1
    # 找到 sample_node 的 flow
    flow_ids = [f["flow_id"] for f in result["flows"]]
    assert str(sample_node_and_user["flow"].id) in flow_ids


@pytest.mark.asyncio
async def test_list_flows_filter_active_only_in_progress(sample_node_and_user) -> None:
    """list_flows filter='active' 仅返回 in_progress 状态。"""
    ctx = _make_ctx()
    result = await tools_read.list_flows(filter="active", ctx=ctx)
    for f in result["flows"]:
        assert f["status"] == "in_progress"


@pytest.mark.asyncio
async def test_list_flows_invalid_filter_raises_tool_error(sample_node_and_user) -> None:
    """list_flows filter='garbage' → ToolError。"""
    from fastmcp.exceptions import ToolError

    ctx = _make_ctx()
    with pytest.raises(ToolError) as ex:
        await tools_read.list_flows(filter="garbage", ctx=ctx)
    assert "filter 必须是" in str(ex.value)


# ---------------------------------------------------------------------------
# 4-5: get_flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_flow_not_found_raises_tool_error(db_session) -> None:
    """get_flow 不存在的 UUID → ToolError "未找到"。"""
    import uuid

    from fastmcp.exceptions import ToolError

    ctx = _make_ctx()
    with pytest.raises(ToolError) as ex:
        await tools_read.get_flow(str(uuid.uuid4()), ctx=ctx)
    assert "未找到" in str(ex.value)


@pytest.mark.asyncio
async def test_get_flow_existing_returns_dag_markdown(sample_node_and_user) -> None:
    """get_flow 存在 → 返回 flow + nodes + dag_markdown 非空。"""
    ctx = _make_ctx()
    flow_id = str(sample_node_and_user["flow"].id)
    result = await tools_read.get_flow(flow_id, ctx=ctx)
    assert "flow" in result
    assert "nodes" in result
    assert "dag_markdown" in result
    assert result["flow"]["flow_id"] == flow_id
    assert len(result["nodes"]) >= 1
    assert "graph TD" in result["dag_markdown"]
    assert "上级审批" in result["dag_markdown"]


# ---------------------------------------------------------------------------
# 6: get_node_form
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_node_form_returns_assignee_and_payload(sample_node_and_user) -> None:
    """get_node_form 已知节点 → 返回 assignee + payload + node。"""
    ctx = _make_ctx(sub="li.si", role="manager")
    flow_id = str(sample_node_and_user["flow"].id)
    node_id = str(sample_node_and_user["node"].id)
    result = await tools_read.get_node_form(flow_id, node_id, ctx=ctx)
    assert result["node"]["id"] == node_id
    assert result["node"]["title"] == "上级审批"
    assert result["assignee"] == sample_node_and_user["user"].username
    assert result["querier_sub"] == "li.si"


# ---------------------------------------------------------------------------
# 7: get_user_assignments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_assignments_lists_pending_nodes(two_flows_with_nodes) -> None:
    """get_user_assignments(user.username) → 返回该用户分配的所有 waiting_human 节点。"""
    ctx = _make_ctx()
    username = two_flows_with_nodes["user"].username
    result = await tools_read.get_user_assignments(username, ctx=ctx)
    assert result["total"] >= 2
    node_ids = {a["node_id"] for a in result["assignments"]}
    assert str(two_flows_with_nodes["node_a"].id) in node_ids
    assert str(two_flows_with_nodes["node_b"].id) in node_ids


# ---------------------------------------------------------------------------
# 8: get_final_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_final_summary_returns_markdown_with_ai_disclaimer(
    sample_node_and_user, db_session
) -> None:
    """get_final_summary 有 node_results → 返回 markdown + ai_disclaimer。"""
    # 给 sample flow 写入 node_results
    flow = sample_node_and_user["flow"]
    flow.context = {
        "node_results": [
            {
                "node_name": "manager_review",
                "node_title": "上级审批",
                "actor": "li.si",
                "action": "advance",
                "result_text": "已审批通过",
            }
        ]
    }
    db_session.add(flow)
    await db_session.commit()

    ctx = _make_ctx()
    result = await tools_read.get_final_summary(str(flow.id), ctx=ctx)
    assert "summary_markdown" in result
    assert "ai_disclaimer" in result
    assert result["ai_disclaimer"] == AI_DISCLAIMER
    assert "上级审批" in result["summary_markdown"]


# ---------------------------------------------------------------------------
# 9: get_handover_docs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_handover_docs_returns_list_from_context(
    sample_node_and_user, db_session
) -> None:
    """get_handover_docs 流程 ctx.handover_docs → 返回 list。"""
    flow = sample_node_and_user["flow"]
    flow.context = {
        "handover_docs": [
            {
                "node_name": "manager_review",
                "node_title": "上级审批",
                "url": "https://outline.example.com/doc/abc",
                "title": "[离职交接] zhang.san · 上级审批",
                "provider": "outline",
            }
        ]
    }
    db_session.add(flow)
    await db_session.commit()

    ctx = _make_ctx()
    result = await tools_read.get_handover_docs(str(flow.id), ctx=ctx)
    assert result["total"] == 1
    assert result["docs"][0]["url"] == "https://outline.example.com/doc/abc"


# ---------------------------------------------------------------------------
# 10: get_meeting_summary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_meeting_summary_empty_id_raises(db_session) -> None:
    """get_meeting_summary meeting_id='' → ToolError "不能为空"。"""
    from fastmcp.exceptions import ToolError

    ctx = _make_ctx()
    with pytest.raises(ToolError) as ex:
        await tools_read.get_meeting_summary("", ctx=ctx)
    assert "不能为空" in str(ex.value)
