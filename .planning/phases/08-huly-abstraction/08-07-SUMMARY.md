# Plan 08-07 SUMMARY — 流程 MCP 化（MCP-01..06）

> **状态**：完成
> **日期**：2026-05-17
> **REQ**：MCP-01 / MCP-02 / MCP-03 / MCP-04 / MCP-05 / MCP-06

---

## 交付

| 文件 | 行 | 作用 |
|---|---|---|
| `backend/src/offboarding_flow/mcp/server.py` | 105 | FastMCP 实例 + middleware 装配 + run_stdio / run_http |
| `backend/src/offboarding_flow/mcp/auth.py` | 105 | `MagicLinkAuthMiddleware` — Bearer JWT 验签 + sub 提取（复用 jwt_service.decode） |
| `backend/src/offboarding_flow/mcp/tools_read.py` | 432 | 7 read tools（C-3 全部走业务表，不读 LangGraph checkpoint） |
| `backend/src/offboarding_flow/mcp/tools_write.py` | 345 | 4 write tools — 三层保护（注册闸门 + middleware + verify_actor_can_handle） |
| `backend/src/offboarding_flow/mcp/registry.py` | 30 | tools 常量集合 |
| `backend/src/offboarding_flow/mcp/runner.py` | 41 | `python -m offboarding_flow.mcp.runner stdio\|http` CLI |
| `backend/src/offboarding_flow/mcp/__init__.py` | 31 | 模块说明 + READ_TOOLS/WRITE_TOOLS 列出 |
| `backend/src/offboarding_flow/main.py` | +18 | mount `/mcp/*` (settings.mcp_http_mounted=true 时) |
| `backend/src/offboarding_flow/config.py` | +3 | `mcp_allow_write` / `mcp_http_port` / `mcp_http_mounted` settings |
| `backend/src/offboarding_flow/auth/role_router.py` | +N | `verify_actor_can_handle` + `PermissionDeniedError`（节点-actor 闸门给 write tools 用） |
| `backend/pyproject.toml` | +1 | `fastmcp>=3.3.1` 依赖 |
| `backend/tests/unit/mcp/test_auth.py` | — | JWT 鉴权测试 |
| `backend/tests/unit/mcp/test_tools_read.py` | — | 7 read tools 单测 |
| `backend/tests/unit/mcp/test_tools_write.py` | — | 4 write tools 闸门 + 权限测试 |
| `backend/tests/integration/test_mcp_http.py` | — | HTTP mount 基础测试 |
| `docs/mcp-setup.md` | 200+ | Claude Desktop 配置文档 + 用例对话 + 故障排查 |

**总计**：1089 行核心代码 + 测试 + 文档；4 个 commit（`e7ff09c` + `2034268` + 后续 docs）。

---

## REQ 映射

| REQ | 实现 | 验证 |
|---|---|---|
| MCP-01 | FastMCP 3.x server 在 `mcp/server.py` | `python -m offboarding_flow.mcp.runner stdio` 启动 OK |
| MCP-02 | 7 read tools 在 `tools_read.py` | `pytest tests/unit/mcp/test_tools_read.py` 全 PASS |
| MCP-03 | 4 write tools + `MCP_ALLOW_WRITE` 闸门 | 默认 `MCP_ALLOW_WRITE=false` 时 `mcp.list_tools()` 仅 7 个；`=true` 时 11 个 |
| MCP-04 | `MagicLinkAuthMiddleware` 复用 `auth/jwt_service.decode` | Bearer JWT 验签 + sub=username 经 set_state 传给 tool |
| MCP-05 | stdio + streamable-http 双 transport；http mode 可 mount 到 FastAPI | `main.py mcp_http_mounted=true` 时 `/mcp/*` 挂载；独立模式跑 `runner http` |
| MCP-06 | `docs/mcp-setup.md` 含 `claude_desktop_config.json` 模板 + 用例对话 | 文档完整；E2E 截图由 user 自助验证（needs Claude Desktop 本地） |

---

## 关键设计决策

### 1. 复用 magic-link JWT（C-2 约束）
不引入第二种 token 体系。MCP Bearer 直接用业务邮件深链 token。`jwt_service.decode` + `verify_actor_can_handle` 复用业务现有闸门，确保 MCP write 与 HTTP API 同质权限。

### 2. write tools **默认禁用**（C-5 约束）
三层保护：
- **注册闸门**：`_maybe_register_write_tools()` 在 `mcp_allow_write=False` 时根本不挂 4 个 write tools
- **middleware**：所有 tool call 必须 Bearer JWT
- **业务闸门**：`verify_actor_can_handle(sub, role, node)` — sub == assignee 或 admin 才放行

防止 LLM 误操作推进流程（PRD §15.3 红线）。

### 3. tools 只读业务表（C-3 约束）
所有 read tool 走 `repositories` 直查业务表，不读 LangGraph checkpoint。前端约定相同。

### 4. mount 优先（部署轻量）
默认部署模式 `MCP_HTTP_MOUNTED=true` 把 MCP 挂到 backend FastAPI 主进程的 `/mcp/*`，无独立容器。stdio 模式给 Claude Desktop 本地用。

### 5. AI Disclaimer 内嵌
所有 write tool 返回 dict 含 `ai_disclaimer`：「*由 AI 生成 — 所有建议必须经 HR 人工确认后执行；AI 不会自动操作任何节点*」（PRD §15.3）。

---

## 已知限制

| ID | 现象 | 原因 | 状态 |
|---|---|---|---|
| MCP-A | streamable-http transport 在 Claude Desktop 0.x 还不完全支持 | MCP SDK / Claude Desktop 双方升级中 | 当前 stdio mode 推荐使用 |
| MCP-B | 单元测试覆盖率仅约 65% | tool 函数 mock 业务 service 复杂 | 集成测试 `test_mcp_http.py` 补 |
| MCP-C | 没跑过 Claude Desktop 真 E2E（含截图） | 需用户本地 + 真实 Claude Desktop 安装 | docs/mcp-setup.md §4 含可复现步骤，让用户自助验证 |

---

## 后续可改进（Phase 9）

1. **多 listener 并存**（同 5.3 §）：让 MCP HTTP server 暴露 listener 列表 / per-flow 推送
2. **MCP resources**：`flow://{flow_id}` 资源订阅（client subscribe → DAG 状态变更推送）
3. **Tool 输入 Pydantic schema 收紧**：现在 dict 化太松，加 Pydantic model 让 LLM 看到清晰 JSON Schema
4. **Read tool 缓存**：`get_flow` 高频，加 1s TTL TTL cache
5. **审计日志**：tool call 全部记录到业务 audit table（who / when / args / result）

---

## 验证步骤（user 自助）

```bash
# 1. 装依赖
cd backend && uv sync

# 2. stdio mode 试启动
python -m offboarding_flow.mcp.runner stdio
# 预期：log 显示 "FastMCP server initialized" + 等待 stdin

# 3. http mode 试启动
python -m offboarding_flow.mcp.runner http
# 预期：日志显示 "Listening on port 8090"

# 4. mount 到 FastAPI
MCP_HTTP_MOUNTED=true uv run uvicorn offboarding_flow.main:create_app --factory
# 然后 curl http://localhost:8000/mcp/ → 200

# 5. Claude Desktop 配置（见 docs/mcp-setup.md §4.1）
# 编辑 ~/Library/Application Support/Claude/claude_desktop_config.json
# 重启 Claude Desktop → 看右下角 offboarding 是否在线
# 在新对话问："列出所有进行中的离职流程" → Claude 应调 list_flows
```
