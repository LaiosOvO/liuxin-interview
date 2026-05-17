"""MCP tools 常量注册表（MCP-02 + MCP-03）。

集中暴露 read / write tool 名称，给 middleware / 测试 / 文档共享。
- 新增 read tool：append READ_TOOLS + 在 tools_read.py 加 @mcp.tool
- 新增 write tool：append WRITE_TOOLS + 在 tools_write.py 加 @mcp.tool
"""

from __future__ import annotations

# 7 个 read tools — 默认全开（业务表只读，不影响流程状态）
READ_TOOLS: list[str] = [
    "list_flows",
    "get_flow",
    "get_node_form",
    "get_user_assignments",
    "get_handover_docs",
    "get_final_summary",
    "get_meeting_summary",
]

# 4 个 write tools — 默认禁（需 MCP_ALLOW_WRITE=true）
WRITE_TOOLS: list[str] = [
    "advance_node",
    "return_node",
    "reject_node",
    "submit_handover_doc",
]


__all__ = ["READ_TOOLS", "WRITE_TOOLS"]
