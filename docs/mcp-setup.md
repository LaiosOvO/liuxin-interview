# offboarding-flow MCP Server 配置

> Phase 8 / Plan 07 — 用 [FastMCP](https://gofastmcp.com/) 把离职流程数据暴露为 [Model Context Protocol](https://modelcontextprotocol.io/) tools，让 LLM 客户端（Claude Desktop / Cursor / 自建 agent）直接调用。

---

## 1. 提供的 Tools

### 1.1 Read tools（7 个，默认开启）

| Tool | 作用 | 用例 |
|---|---|---|
| `list_flows` | 列出所有流程（按 status 过滤）| 「列出所有进行中的离职」|
| `get_flow` | 拿单个流程的完整 DAG + 进度 | 「it.charlie 的流程到哪一步了」|
| `get_node_form` | 拿节点表单的填写状态 + 历史 | 「设备归还节点的 result_text 是什么」|
| `get_user_assignments` | 列某用户的待处理节点 | 「我负责的待审批节点有哪些」|
| `get_handover_docs` | 列某流程的所有节点交接文档 URL | 「it.charlie 的交接文档链接」|
| `get_final_summary` | 拿流程总报告 URL + 摘要 | 「it.charlie 的离职总报告」|
| `get_meeting_summary` | 列会议总结文档 | 「上周 IT 会议总结」|

### 1.2 Write tools（4 个，**默认禁用**）

需 `.env` 里 `MCP_ALLOW_WRITE=true` 才会注册到 MCP 服务：

| Tool | 作用 |
|---|---|
| `advance_node` | 推进节点 |
| `return_node` | 退回节点 |
| `reject_node` | 拒绝节点 |
| `submit_handover_doc` | 提交节点交接文档 URL |

**三层保护**：
1. 注册闸门 — `MCP_ALLOW_WRITE=false` 时 import 期就不挂这些 tools
2. middleware 鉴权 — 必须带 Bearer JWT，验签 + sub 提取
3. 业务闸门 — `verify_actor_can_handle(sub, role, node)`：仅 assignee 或 admin 放行

**AI 边界**：所有 write tool 返回 dict 含 `ai_disclaimer` 字段，明确告知最终决策必须人工确认（PRD §15.3）。

---

## 2. 鉴权（MCP-04）

复用业务现有的 **magic-link JWT**（同一套 `auth/jwt_service.encode/decode`），不引入第二种 token 体系。

```
HTTP 请求头：
Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...
```

- token 通过任何业务邮件深链（已含 `?token=...`）拿到；用户复制后填进 MCP 客户端
- `MagicLinkAuthMiddleware.on_call_tool` 验签 → 提取 `sub`（=username）→ set_state 给后续 tool 使用
- stdio mode 默认信任本地（subprocess 在 user 进程内）；http mode 强制 Bearer

---

## 3. Transport 两种 mode（MCP-05）

### 3.1 stdio mode — Claude Desktop / Cursor 直连

适用于本地 LLM 客户端 subprocess 启动。

```bash
# 直接跑（开发期）
python -m offboarding_flow.mcp.runner stdio

# 或通过 entry_point
offboarding-mcp-stdio
```

### 3.2 streamable-http mode — Web LLM agent

MCP 2025-11 spec 替代 deprecated SSE。两种部署方式：

**3.2a 独立 server**（与业务进程隔离）：

```bash
python -m offboarding_flow.mcp.runner http
# 默认端口 settings.mcp_http_port=8090
```

**3.2b mount 到 backend FastAPI**（无单独容器，推荐演示部署）：

```ini
# .env
MCP_HTTP_MOUNTED=true
```

`main.py lifespan` 自动 `app.mount("/mcp", mcp.http_app())`，访问 `http://192.168.2.44/mcp/`。

---

## 4. Claude Desktop 配置

### 4.1 stdio 模式（推荐 — 本地）

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`（Mac）/
`%APPDATA%\Claude\claude_desktop_config.json`（Win）：

```json
{
  "mcpServers": {
    "offboarding": {
      "command": "/Users/admin/ai/resume/interview/liuxin/hr/backend/.venv/bin/python",
      "args": [
        "-m",
        "offboarding_flow.mcp.runner",
        "stdio"
      ],
      "env": {
        "PYTHONPATH": "/Users/admin/ai/resume/interview/liuxin/hr/backend/src",
        "DATABASE_URL": "postgresql+asyncpg://offboarding:offboarding@192.168.2.44:5433/offboarding",
        "JWT_SECRET": "<同 backend .env 的 JWT_SECRET>",
        "REDIS_URL": "redis://192.168.2.44:6380/0",
        "MCP_ALLOW_WRITE": "false"
      }
    }
  }
}
```

重启 Claude Desktop，在新对话里看右下角应能看到 `offboarding` MCP 已连接 + 7 个 tools 可调。

### 4.2 streamable-http 模式（远程团队共享）

```json
{
  "mcpServers": {
    "offboarding-remote": {
      "url": "http://192.168.2.44/mcp/",
      "headers": {
        "Authorization": "Bearer eyJ0eXAi...<你的 magic JWT>"
      }
    }
  }
}
```

> Claude Desktop 0.x 不全支持 http transport；目前 stdio 更稳。

---

## 5. 用例对话

让 Claude 调 MCP tools 的典型对话：

```
You: it.charlie 这个员工的离职流程到哪一步了？

Claude: 让我查一下。
[Tool call: get_user_assignments(username="it.charlie")]
[Tool call: get_flow(flow_id="e96da4a2-...")]

it.charlie 的离职流程 `e96da4a2-5bdd-450f-b6c3-3c6ef4e4e1fb`：
- 状态：completed
- 进度：11/11 节点全部 done
- DAG：apply → manager_review → hr_initial → 5 并行 → hr_final → applicant_final_confirm → archive
- 总报告：http://192.168.2.44:3001/doc/itcharlie-jsbr0cFFDK
- 9 个节点交接文档已生成（在 Outline "离职 · it.charlie" Space）

*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*
```

---

## 6. 故障排查

| 现象 | 原因 | 解决 |
|---|---|---|
| `offboarding` MCP 显示离线 | python path 错 / venv 缺依赖 | 跑 `python -m offboarding_flow.mcp.runner stdio` 看错误 |
| Bearer 鉴权 401 | JWT 过期（默认 7 天）/ JWT_SECRET 不匹配 | 重新点最近邮件深链拿新 token |
| write tool 报"not registered" | `MCP_ALLOW_WRITE` 没设 true | 改 .env + 重启 |
| write tool 报"权限不足" | sub 不是节点 assignee | 用对应角色的 token / 用 admin token |
| HTTP mount 路径 404 | `MCP_HTTP_MOUNTED=false` | 设 true + 重启 backend |

---

## 7. 关键文件

```
backend/src/offboarding_flow/mcp/
  server.py         FastMCP 实例 + middleware 装配 + run_stdio / run_http
  auth.py           MagicLinkAuthMiddleware（复用 magic-link JWT）
  tools_read.py     7 read tools
  tools_write.py    4 write tools（默认禁用）
  registry.py       tools 常量注册
  runner.py         CLI 入口 `python -m offboarding_flow.mcp.runner stdio|http`
  __init__.py
```

测试：`backend/tests/unit/mcp/test_{auth,tools_read,tools_write}.py` + `backend/tests/integration/test_mcp_http.py`。
