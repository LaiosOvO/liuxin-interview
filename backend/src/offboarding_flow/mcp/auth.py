"""MagicLinkAuthMiddleware（MCP-04）— 复用 magic-link JWT 做 MCP Bearer 鉴权。

约定（C-2 + RESEARCH §Pattern 4）：
- stdio 模式（headers 为空 dict）→ 信任本地 subprocess，set_state user_sub=
  'local-stdio' + user_role='admin'
- HTTP 模式 + 缺 Authorization → 抛 ToolError "缺少 Bearer token"
- HTTP 模式 + 错 token → 抛 ToolError "无效"
- HTTP 模式 + 合法 magic-link JWT → 复用 auth.jwt_service.decode → set_state
  user_sub + user_role

关键点（RESEARCH Pitfall #7）：
- stateless_http=True 时 ctx state 是 per-request，**同一调用链**内 tool 函数
  立即读没问题；不要假设跨请求依赖 state
- get_http_headers() 默认 strip authorization header（安全默认），需要显式
  include={"authorization"} 才能拿到

实现细节：
- 失败统一抛 ToolError（FastMCP 自动转 MCP 错误响应，不暴露 stack trace）
- 不直接 except 业务侧的 AuthError —— from e 让追踪链完整但对 LLM 客户端只
  显示 ToolError 包装后的中文 message
"""

from __future__ import annotations

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext

from offboarding_flow.auth import jwt_service

logger = logging.getLogger(__name__)

# stdio 模式默认身份（信任本地 subprocess，Claude Desktop 场景）
_LOCAL_STDIO_SUB = "local-stdio"
_LOCAL_STDIO_ROLE = "admin"


class MagicLinkAuthMiddleware(Middleware):
    """复用 magic-link JWT 做 MCP Bearer 鉴权。

    使用方式（server.py 内）：
        mcp = FastMCP("offboarding-flow")
        mcp.add_middleware(MagicLinkAuthMiddleware())

    Tool 函数读 sub / role：
        @mcp.tool
        async def my_tool(arg: str, ctx: Context = None) -> dict:
            sub = ctx.get_state("user_sub")
            role = ctx.get_state("user_role")
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        """Tool 调用前拦截 — 注入 user_sub / user_role 到 ctx state。

        用 serializable=False（per-request 内存）防止两个问题：
        1. 不必要的 JSON 序列化 + 远端 state store IO
        2. set_state(serializable=False) 是同步函数（直接 dict 写入），不用 await
        """
        # 显式 include authorization — get_http_headers 默认会 strip 这个 header
        headers = get_http_headers(include={"authorization"})

        fc = context.fastmcp_context
        if fc is None:
            # 防御性 — middleware 总是有 fastmcp_context；遇到 None 直接放行
            logger.warning("[mcp.auth] MiddlewareContext.fastmcp_context 为 None — 跳过鉴权")
            return await call_next(context)

        # stdio 模式 headers 为空（FastMCP 无 HTTP 请求上下文）
        if not headers:
            await fc.set_state("user_sub", _LOCAL_STDIO_SUB, serializable=False)
            await fc.set_state("user_role", _LOCAL_STDIO_ROLE, serializable=False)
            logger.debug("[mcp.auth] stdio 模式 — 信任本地 sub=%s", _LOCAL_STDIO_SUB)
            return await call_next(context)

        # HTTP 模式 — 必须 Bearer JWT
        auth_header = headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.warning("[mcp.auth] HTTP 模式缺少 Bearer header")
            raise ToolError("MCP 请求缺少 Bearer token；请在 Authorization header 用 Bearer <jwt>")

        token = auth_header.removeprefix("Bearer ").strip()
        if not token:
            raise ToolError("MCP 请求 Bearer token 为空")

        try:
            payload = jwt_service.decode(token)
        except Exception as e:
            # 不暴露内部异常细节给 LLM 客户端
            logger.warning("[mcp.auth] Bearer token 解码失败: %s", type(e).__name__)
            raise ToolError(f"Bearer token 无效: {type(e).__name__}") from e

        # 注入到 ctx state；tool 函数 ctx.get_state 立即可读
        await fc.set_state("user_sub", payload.sub, serializable=False)
        await fc.set_state("user_role", payload.role, serializable=False)
        logger.info(
            "[mcp.auth] HTTP 鉴权通过 sub=%s role=%s",
            payload.sub,
            payload.role,
        )
        return await call_next(context)


__all__ = ["MagicLinkAuthMiddleware"]
