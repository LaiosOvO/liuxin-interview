"""FastMCP 实例 + middleware 装配 + tool 注册入口（MCP-01）。

启动顺序：
1. get_settings() — 读 MCP_ALLOW_WRITE / MCP_HTTP_PORT 等配置
2. FastMCP("offboarding-flow") — 实例化
3. mcp.add_middleware(MagicLinkAuthMiddleware()) — Bearer JWT 鉴权
4. `import tools_read` — 触发 7 个 read @mcp.tool 注册
5. _maybe_register_write_tools() — 仅 settings.mcp_allow_write=True 时 import
   tools_write，触发 4 个 write @mcp.tool 注册（启动期 env 真禁用，
   RESEARCH Pitfall #8）

对外暴露：
- `mcp`  — FastMCP 实例，tools_read / tools_write 用 @mcp.tool 装饰
- `run_stdio()` — Claude Desktop / Cursor stdio mode
- `run_http()` — 独立 HTTP server（streamable-http transport）
- 也可以从 main.py mount 到 FastAPI 的 /mcp/* 路径（settings.mcp_http_mounted）

注意：
- 本模块 import 顺序很关键：先 mcp 实例 → 再 add middleware → 再 import
  tools_read（触发注册）；不要把 tools_read 的 import 放在 server.py 顶部，
  因为 tools_read 也要 from server import mcp（循环依赖）
"""

from __future__ import annotations

import logging

from fastmcp import FastMCP

from offboarding_flow.config import get_settings
from offboarding_flow.mcp.auth import MagicLinkAuthMiddleware

logger = logging.getLogger(__name__)

_settings = get_settings()

# FastMCP 实例 — 名称会出现在 LLM 客户端的 MCP server 列表
mcp = FastMCP("offboarding-flow")

# Bearer JWT 鉴权 middleware（C-2 复用 magic-link JWT）
mcp.add_middleware(MagicLinkAuthMiddleware())

# 触发 7 个 read tools 注册（必须在 mcp 实例化后 import）
# 等同于在 server.py 末尾写 from offboarding_flow.mcp import tools_read
# 用 noqa 让 ruff 不报 unused import
from offboarding_flow.mcp import tools_read  # noqa: E402, F401


def _maybe_register_write_tools() -> None:
    """启动期判 env 决定是否注册 write tools（RESEARCH Pitfall #8 真禁用而非描述）。

    - settings.mcp_allow_write=False（默认）→ 不 import tools_write，4 个 tool
      根本不在 mcp 实例 tool 列表里，LLM 看不到也调不到
    - settings.mcp_allow_write=True → import tools_write，触发 @mcp.tool 注册
    """
    if not _settings.mcp_allow_write:
        logger.info(
            "[mcp.server] MCP_ALLOW_WRITE=false（默认）— write tools 不注册（只暴露 7 read tools）"
        )
        return
    logger.warning(
        "[mcp.server] MCP_ALLOW_WRITE=true — 启用 4 个 write tools（"
        "advance_node/return_node/reject_node/submit_handover_doc）"
        "；LLM 可改流程状态，请确保业务侧审批"
    )
    # 触发 4 个 write tools 注册
    from offboarding_flow.mcp import tools_write  # noqa: F401


# 模块底部调一次（import 时执行）
_maybe_register_write_tools()


# ---------------------------------------------------------------------------
# Transport entry helpers（runner.py 用）
# ---------------------------------------------------------------------------


def run_stdio() -> None:
    """stdio mode — Claude Desktop / Cursor subprocess 用。"""
    logger.info("[mcp.server] starting stdio transport")
    mcp.run()


def run_http() -> None:
    """HTTP mode — 独立 HTTP server（streamable-http, MCP 2025-11 spec）。

    用 stateless_http=True 让生产可横向扩展（RESEARCH Pitfall #7）；
    state 是 per-request 的，middleware on_call_tool 内 set_state →
    同一调用链 tool 立即可读。
    """
    logger.info(
        "[mcp.server] starting http transport: port=%s path=/mcp",
        _settings.mcp_http_port,
    )
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=_settings.mcp_http_port,
        path="/mcp",
        stateless_http=True,
    )


__all__ = ["mcp", "run_http", "run_stdio"]
