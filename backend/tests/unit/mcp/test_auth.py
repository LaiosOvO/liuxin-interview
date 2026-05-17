"""MagicLinkAuthMiddleware 单元测试（MCP-04）。

覆盖：
1. stdio mode（headers={}）→ set_state user_sub=local-stdio + call_next 调用
2. http mode + 缺 Authorization → ToolError 含"缺少 Bearer"
3. http mode + 非 Bearer 前缀 → ToolError "缺少 Bearer"
4. http mode + 无效 JWT → ToolError 含"无效"
5. http mode + 合法 magic-link JWT → set_state user_sub + role 注入
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from offboarding_flow.auth import jwt_service
from offboarding_flow.auth.schemas import JWTPayload
from offboarding_flow.mcp.auth import MagicLinkAuthMiddleware

pytestmark = pytest.mark.unit


def _make_valid_token(sub: str = "hr.alice", role: str = "hr") -> str:
    """构造一个合法 magic-link JWT（用于鉴权 happy path 测试）。"""
    now = int(time.time())
    payload = JWTPayload(
        sub=sub,
        email=f"{sub}@demo.local",
        role=role,
        flow_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        node_name="manager_review",
        allowed_actions=["advance", "return", "reject"],
        iat=now,
        exp=now + 600,
        jti=uuid.uuid4().hex,
    )
    return jwt_service.encode(payload)


def _make_context() -> MagicMock:
    """伪造 MiddlewareContext + fastmcp_context.set_state（async）。"""
    ctx = MagicMock()
    ctx.fastmcp_context = MagicMock()
    # set_state 是 async — 必须 AsyncMock，不然 await 会报 TypeError
    ctx.fastmcp_context.set_state = AsyncMock()
    return ctx


@pytest.mark.asyncio
async def test_stdio_mode_sets_local_identity_and_calls_next() -> None:
    """stdio mode（headers={}）→ set_state local-stdio + call_next 被调用。"""
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock(return_value="next_result")

    # mock get_http_headers 返回空 dict（stdio 默认）
    with patch("offboarding_flow.mcp.auth.get_http_headers", return_value={}):
        result = await middleware.on_call_tool(ctx, call_next)

    assert result == "next_result"
    call_next.assert_awaited_once_with(ctx)
    # set_state 被调用两次：user_sub + user_role（serializable=False per-request）
    ctx.fastmcp_context.set_state.assert_any_await("user_sub", "local-stdio", serializable=False)
    ctx.fastmcp_context.set_state.assert_any_await("user_role", "admin", serializable=False)


@pytest.mark.asyncio
async def test_http_mode_missing_authorization_raises() -> None:
    """http mode + 缺 Authorization → ToolError 含"缺少 Bearer"。"""
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock()

    # headers 非空但缺 authorization
    with patch(
        "offboarding_flow.mcp.auth.get_http_headers",
        return_value={"user-agent": "claude"},
    ):
        with pytest.raises(ToolError) as ex:
            await middleware.on_call_tool(ctx, call_next)

    assert "缺少 Bearer" in str(ex.value)
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_mode_non_bearer_prefix_raises() -> None:
    """http mode + 错前缀（Basic xxx）→ ToolError "缺少 Bearer"。"""
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock()

    with patch(
        "offboarding_flow.mcp.auth.get_http_headers",
        return_value={"authorization": "Basic abc123"},
    ):
        with pytest.raises(ToolError) as ex:
            await middleware.on_call_tool(ctx, call_next)

    assert "缺少 Bearer" in str(ex.value)
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_mode_invalid_jwt_raises() -> None:
    """http mode + 无效 JWT → ToolError "无效"。"""
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock()

    with patch(
        "offboarding_flow.mcp.auth.get_http_headers",
        return_value={"authorization": "Bearer not-a-real-jwt"},
    ):
        with pytest.raises(ToolError) as ex:
            await middleware.on_call_tool(ctx, call_next)

    assert "无效" in str(ex.value)
    call_next.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_mode_valid_jwt_sets_sub_and_role() -> None:
    """http mode + 合法 magic-link JWT → set_state user_sub/user_role 注入。"""
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock(return_value="ok")

    token = _make_valid_token(sub="hr.alice", role="hr")
    with patch(
        "offboarding_flow.mcp.auth.get_http_headers",
        return_value={"authorization": f"Bearer {token}"},
    ):
        result = await middleware.on_call_tool(ctx, call_next)

    assert result == "ok"
    call_next.assert_awaited_once_with(ctx)
    ctx.fastmcp_context.set_state.assert_any_await("user_sub", "hr.alice", serializable=False)
    ctx.fastmcp_context.set_state.assert_any_await("user_role", "hr", serializable=False)


@pytest.mark.asyncio
async def test_http_mode_empty_bearer_value_raises() -> None:
    """http mode + Authorization: Bearer 后面是空串 → ToolError "Bearer token 为空"。

    额外加强测试 — 防御性边界。
    """
    middleware = MagicLinkAuthMiddleware()
    ctx = _make_context()
    call_next = AsyncMock()

    with patch(
        "offboarding_flow.mcp.auth.get_http_headers",
        return_value={"authorization": "Bearer "},
    ):
        with pytest.raises(ToolError) as ex:
            await middleware.on_call_tool(ctx, call_next)

    assert "为空" in str(ex.value)
