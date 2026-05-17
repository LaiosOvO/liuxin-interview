"""MCP entry — `python -m offboarding_flow.mcp.runner stdio|http`（MCP-05）。

用法：
    # stdio mode（Claude Desktop / Cursor subprocess）
    python -m offboarding_flow.mcp.runner stdio

    # 独立 http server（streamable-http, MCP 2025-11 spec，替代 deprecated SSE）
    python -m offboarding_flow.mcp.runner http

也可以通过 settings.mcp_http_mounted=True 让 backend FastAPI 在 /mcp/* 路径
mount 同一个 mcp 实例（main.py 处理，避免多容器；推荐演示部署）。
"""

from __future__ import annotations

import logging
import sys

from offboarding_flow.mcp.server import run_http, run_stdio

_VALID_MODES = ("stdio", "http")


def main() -> None:
    """模块入口：argv[1] 选 stdio/http；缺省 stdio；错误 exit(2)。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    if mode not in _VALID_MODES:
        print(
            f"Usage: python -m offboarding_flow.mcp.runner [{ '|'.join(_VALID_MODES) }]",
            file=sys.stderr,
        )
        sys.exit(2)
    {"stdio": run_stdio, "http": run_http}[mode]()


if __name__ == "__main__":
    main()
