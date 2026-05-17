"""Phase 8 / Plan 07 — 流程 MCP 化（MCP-01..06）。

把离职流程能力暴露为 MCP（Model Context Protocol）tools，让 LLM 客户端
（Claude Desktop / Cursor / 任意 MCP-aware agent）能直接读流程状态 +（可选）
推进节点。

三件套：
- server.py — FastMCP 实例 + middleware 装配 + tool 注册入口
- auth.py — MagicLinkAuthMiddleware（复用 magic-link JWT，C-2 不引入第二
  token 体系）
- tools_read.py / tools_write.py — 11 个 tool 实现
  - 7 read tools 默认开
  - 4 write tools 默认禁（PRD §15.3 + RESEARCH Pitfall #8），需
    `MCP_ALLOW_WRITE=true` 启用

约定（CLAUDE.md + PRD §15.3）：
- MCP tools 全部走业务 DB（`app.*` schema），**不直接读 LangGraph
  checkpoint**（C-3 双层状态分离）
- write tools 三层保护：注册闸门 → middleware 鉴权 → verify_actor_can_handle
- AI 输出必须带 disclaimer

启动模式：
- stdio （`python -m offboarding_flow.mcp.runner stdio`）— Claude Desktop 用
- http  （`python -m offboarding_flow.mcp.runner http`）— 独立 HTTP server
- mount 到 FastAPI（`settings.mcp_http_mounted=True`，main.py mount /mcp/*）—
  避免多容器，推荐演示部署
"""

from offboarding_flow.mcp.registry import READ_TOOLS, WRITE_TOOLS

__all__ = ["READ_TOOLS", "WRITE_TOOLS"]
