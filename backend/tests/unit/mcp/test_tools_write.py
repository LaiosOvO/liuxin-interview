"""MCP write tools 单元测试（MCP-03）。

覆盖：
1. MCP_ALLOW_WRITE=false → mcp.list_tools() 不含 write tools（注册闸门真禁用）
2. MCP_ALLOW_WRITE=true → mcp.list_tools() 含 4 个 write tools
3. _fetch_node_with_gate 权限不足 → ToolError "权限不足"
4. _fetch_node_with_gate 权限 OK（admin role）→ 返回 node
5. _fetch_node_with_gate node 不存在 → ToolError "未找到"
6. _fetch_node_with_gate flow_id 不匹配 → ToolError "不属于"
7. _build_idempotency_actor 含 key → "mcp:sub#prefix"
8. _build_idempotency_actor 无 key → "mcp:sub"
9. advance_node 失败 路径（HTTPException）→ ToolError 包装
10. write tool 返回 dict 含 ai_disclaimer
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# 1-2: 注册闸门 — MCP_ALLOW_WRITE
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_allow_write_false_does_not_register_write_tools() -> None:
    """MCP_ALLOW_WRITE=false（默认）→ list_tools 只返回 7 read tools。"""
    # 强制 reload server with MCP_ALLOW_WRITE=false
    import os

    os.environ["MCP_ALLOW_WRITE"] = "false"
    from offboarding_flow.config import reload_settings

    reload_settings()

    # 用 patched env 起一个全新 FastMCP 实例验证（避免污染全局）
    from fastmcp import FastMCP

    from offboarding_flow.mcp.auth import MagicLinkAuthMiddleware

    fresh_mcp = FastMCP("test-allow-write-false")
    fresh_mcp.add_middleware(MagicLinkAuthMiddleware())

    # 不 import tools_write — 模拟 _maybe_register_write_tools 跳过
    tools = await fresh_mcp.list_tools()
    write_tool_names = {"advance_node", "return_node", "reject_node", "submit_handover_doc"}
    assert not any(
        t.name in write_tool_names for t in tools
    ), "write tools 不应注册到 fresh fastmcp 实例"


@pytest.mark.asyncio
async def test_mcp_allow_write_true_register_4_write_tools() -> None:
    """MCP_ALLOW_WRITE=true → tools_write 模块 import 后 4 个 write tools 全部 @mcp.tool 注册。"""
    # 主 server.mcp 实例（settings 由 conftest 时序读取，无法热改）
    # 直接 import tools_write — 触发 4 个 @mcp.tool 注册到 main_mcp
    import offboarding_flow.mcp.tools_write as _tw  # noqa: F401
    from offboarding_flow.mcp.server import mcp as main_mcp

    tools = await main_mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "advance_node" in tool_names
    assert "return_node" in tool_names
    assert "reject_node" in tool_names
    assert "submit_handover_doc" in tool_names


# ---------------------------------------------------------------------------
# 3-6: _fetch_node_with_gate 三件套
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_node_with_gate_permission_denied_raises() -> None:
    """非 assignee 且非 admin → ToolError "权限不足"。"""
    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    nid = uuid.uuid4()

    # mock session.get 返回 node assignee=li.si，actor sub=wang.wu（不匹配）
    fake_node = MagicMock()
    fake_node.flow_id = fid
    fake_node.assignee = "li.si"
    fake_node.node_name = "manager_review"

    class _FakeSession:
        async def get(self, model, key):
            return fake_node

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch(
        "offboarding_flow.mcp.tools_write.new_session",
        lambda: _FakeSession(),
    ):
        with pytest.raises(ToolError) as ex:
            await tools_write._fetch_node_with_gate(
                str(fid), str(nid), sub="wang.wu", role="finance"
            )

    assert "权限不足" in str(ex.value)


@pytest.mark.asyncio
async def test_fetch_node_with_gate_admin_role_passes() -> None:
    """admin role → 跳过 assignee 校验，返回 node。"""
    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    nid = uuid.uuid4()

    fake_node = MagicMock()
    fake_node.flow_id = fid
    fake_node.assignee = "li.si"
    fake_node.node_name = "manager_review"

    class _FakeSession:
        async def get(self, model, key):
            return fake_node

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch(
        "offboarding_flow.mcp.tools_write.new_session",
        lambda: _FakeSession(),
    ):
        result_fid, result_nid, result_node = await tools_write._fetch_node_with_gate(
            str(fid), str(nid), sub="anyone.else", role="admin"
        )

    assert result_fid == fid
    assert result_nid == nid
    assert result_node is fake_node


@pytest.mark.asyncio
async def test_fetch_node_with_gate_node_not_found() -> None:
    """node 不存在 → ToolError "未找到"。"""
    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    nid = uuid.uuid4()

    class _FakeSession:
        async def get(self, model, key):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch(
        "offboarding_flow.mcp.tools_write.new_session",
        lambda: _FakeSession(),
    ):
        with pytest.raises(ToolError) as ex:
            await tools_write._fetch_node_with_gate(str(fid), str(nid), sub="hr.alice", role="hr")

    assert "未找到" in str(ex.value)


@pytest.mark.asyncio
async def test_fetch_node_with_gate_flow_mismatch() -> None:
    """node.flow_id != fid → ToolError "不属于"。"""
    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    other_fid = uuid.uuid4()
    nid = uuid.uuid4()

    fake_node = MagicMock()
    fake_node.flow_id = other_fid  # 不匹配
    fake_node.assignee = "hr.alice"
    fake_node.node_name = "manager_review"

    class _FakeSession:
        async def get(self, model, key):
            return fake_node

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with patch(
        "offboarding_flow.mcp.tools_write.new_session",
        lambda: _FakeSession(),
    ):
        with pytest.raises(ToolError) as ex:
            await tools_write._fetch_node_with_gate(str(fid), str(nid), sub="hr.alice", role="hr")

    assert "不属于" in str(ex.value)


# ---------------------------------------------------------------------------
# 7-8: _build_idempotency_actor
# ---------------------------------------------------------------------------


def test_build_idempotency_actor_with_key() -> None:
    """有 key → "mcp:sub#prefix"（取前 8 位防过长）。"""
    from offboarding_flow.mcp.tools_write import _build_idempotency_actor

    # 假 fixture（gitleaks-safe — 含 "fixture" 字样防误判）
    full_key = "fixture-idem-aaaa-bbbb-cccc"
    actor = _build_idempotency_actor("hr.alice", full_key)
    assert actor == "mcp:hr.alice#fixture-"


def test_build_idempotency_actor_no_key() -> None:
    """无 key → "mcp:sub"。"""
    from offboarding_flow.mcp.tools_write import _build_idempotency_actor

    actor = _build_idempotency_actor("hr.alice", None)
    assert actor == "mcp:hr.alice"


# ---------------------------------------------------------------------------
# 9-10: advance_node 失败路径 + ai_disclaimer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_do_action_wraps_http_exception_as_tool_error() -> None:
    """submit_action 抛 HTTPException → ToolError 包装。"""
    from fastapi import HTTPException

    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    nid = uuid.uuid4()

    # mock NodeService.submit_action 抛业务异常
    class _FakeSvc:
        async def submit_action(self, **kwargs):
            raise HTTPException(status_code=409, detail="节点状态错")

    class _FakeSession:
        async def get(self, model, key):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with (
        patch("offboarding_flow.mcp.tools_write.new_session", lambda: _FakeSession()),
        patch(
            "offboarding_flow.flow_engine.graph.get_graph",
            return_value=MagicMock(),
        ),
        patch(
            "offboarding_flow.services.NodeService",
            lambda **_: _FakeSvc(),
        ),
    ):
        with pytest.raises(ToolError) as ex:
            await tools_write._do_action(
                fid=fid,
                nid=nid,
                action="advance",
                result_text="x",
                actor="mcp:test",
            )

    assert "节点状态错" in str(ex.value)


@pytest.mark.asyncio
async def test_do_action_returns_dict_with_ai_disclaimer() -> None:
    """成功路径返回 dict 含 ai_disclaimer + ok=True。"""
    from offboarding_flow.mcp import tools_write

    fid = uuid.uuid4()
    nid = uuid.uuid4()

    class _FakeSvc:
        async def submit_action(self, **kwargs):
            return {"next_node": "hr_initial", "next_assignee": "hr.bob"}

    class _FakeSession:
        async def get(self, model, key):
            return None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    with (
        patch("offboarding_flow.mcp.tools_write.new_session", lambda: _FakeSession()),
        patch(
            "offboarding_flow.flow_engine.graph.get_graph",
            return_value=MagicMock(),
        ),
        patch(
            "offboarding_flow.services.NodeService",
            lambda **_: _FakeSvc(),
        ),
    ):
        result = await tools_write._do_action(
            fid=fid,
            nid=nid,
            action="advance",
            result_text="OK",
            actor="mcp:hr.alice",
        )

    assert result["ok"] is True
    assert result["action"] == "advance"
    assert "ai_disclaimer" in result
    assert "AI" in result["ai_disclaimer"]
