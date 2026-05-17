# FastMCP 3.x 阅读笔记

> 日期: 2026-05-17
> 仓库: https://github.com/jlowin/fastmcp
> 文档: https://gofastmcp.com/getting-started + https://gofastmcp.com/servers/auth/token-verification + https://gofastmcp.com/integrations/claude-desktop
> Stars: 8k+（70% 生产 MCP 服务底座）

## 项目概述

FastMCP 是 Python 写 MCP（Model Context Protocol） server 的 decorator-based 框架。把 FastAPI 风格的"@tool/@resource/@prompt 装饰函数"模式带到 MCP 协议，比裸用官方 `mcp` SDK 少写 60% 样板。

## 技术栈

- Python 3.10+（推荐 3.12+）
- 内部 wrap 官方 `mcp` SDK（FastMCP 在其上提供 decorator + transport + middleware）
- Anthropic 推荐；Cloudflare workers 也用作 reference
- 支持 stdio（默认，Claude Desktop / Cursor 用） + Streamable HTTP（远程 LLM agent 用，2025-11 spec 替代 deprecated SSE）

## 架构要点

### 核心 API（3.3.1+）

```python
from fastmcp import FastMCP, Context
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError

# 1. 实例
mcp = FastMCP("name")

# 2. middleware（拦截 tool 调用）
mcp.add_middleware(MyMiddleware())

# 3. tool（async + Context 注入）
@mcp.tool
async def my_tool(arg: str, ctx: Context = None) -> dict:
    sub = ctx.get_state("user_sub")   # middleware 注入的状态
    return {"result": "..."}

# 4. transport
mcp.run()  # 默认 stdio
mcp.run(transport="streamable-http", host="0.0.0.0", port=7788, path="/mcp", stateless_http=True)

# 5. mount 到 FastAPI（避免多容器）
app.mount("/mcp", mcp.http_app())
```

### Middleware on_call_tool 模式

最关键：用 middleware on_call_tool 做鉴权，比官方 TokenVerifier 子类灵活很多。

```python
class MagicLinkAuthMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers()   # stdio 模式返回 {}
        if not headers:
            # stdio: 信任本地 subprocess
            context.fastmcp_context.set_state("user_sub", "local-stdio")
            context.fastmcp_context.set_state("user_role", "admin")
            return await call_next(context)

        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise ToolError("缺少 Bearer token")
        token = auth.removeprefix("Bearer ").strip()
        try:
            payload = decode(token)  # 复用业务 JWT
        except Exception as e:
            raise ToolError(f"token 无效: {e}") from e
        context.fastmcp_context.set_state("user_sub", payload.sub)
        context.fastmcp_context.set_state("user_role", payload.role)
        return await call_next(context)
```

**关键点**：

- `context.fastmcp_context` 是 FastMCP 的 Context；`set_state`/`get_state` 是 per-request KV
- `stateless_http=True` 时 state 是 per-request，同一 tool 链路内可读，跨请求会丢
- middleware 抛 ToolError → FastMCP 自动转 MCP 错误响应（不暴露 stack trace）

## 可借鉴的设计模式

### 1. 启动期判 env 真禁用 write tools（Pitfall #8）

不能只在描述里写"禁用"，FastMCP 默认所有 `@mcp.tool` 都注册到 server tool 列表，LLM 还是看得到。正确做法：

```python
if settings.mcp_allow_write:
    from offboarding_flow.mcp import tools_write   # 仅在开启时 import 触发 register
```

或者用 `mcp.remove_tool("name")` 启动后摘除，但 import 触发 register 更简洁。

### 2. stateless_http + per-request state（Pitfall #7）

生产 MCP HTTP server 必开 `stateless_http=True`（可横向扩展），但代价是 ctx state 不能跨请求。设计上：

- middleware on_call_tool **同一调用链**内 set_state → tool 函数立即 get_state，OK
- 不要假设 "前次 tool 调用 set 的 state 这次能读到"
- 每次都从 Authorization header 重新 decode

### 3. Tool docstring = LLM 看到的描述

`@mcp.tool` decorator 把函数 docstring 当 tool description 暴露给 LLM。所以 docstring 必须：

- 中文（项目语言）
- 简洁说明"做什么 + 输入输出"
- 写操作显式标"⚠️ 写操作 — 会改变流程状态"
- 提示幂等 idempotency_key 用法

### 4. Tool 函数签名

参数必须有类型注解（FastMCP 用 pydantic 自动生成 JSON Schema 给 LLM）。`ctx: Context = None` 是惯例（FastMCP 自动注入）。返回 dict（JSON-serializable）。

## Claude Desktop 配置陷阱

```json
{
  "mcpServers": {
    "offboarding-flow": {
      "command": "uv",
      "args": [
        "run", "--project", "/绝对路径/to/backend",
        "python", "-m", "offboarding_flow.mcp.runner", "stdio"
      ],
      "env": {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5433",
        "JWT_SECRET": "...",
        "MCP_ALLOW_WRITE": "false"
      }
    }
  }
}
```

**陷阱**：

- `command` 必须是绝对路径或 PATH 内能找到的命令；macOS 的 GUI app 启动的 subprocess **不继承用户 shell 的 PATH** — 推荐 `command: "/Users/.../.local/bin/uv"` 直接给绝对路径
- `--project /绝对路径` 必须传，否则 uv 找不到 pyproject
- `env` 必须显式列出，subprocess 不读 `.env`
- 改配置后必须 **完全退出 Claude Desktop**（Cmd+Q），仅关闭窗口不重启 subprocess
- 日志在 `~/Library/Logs/Claude/mcp-server-offboarding-flow.log`

## 与本项目的关系

### 文件落位

```
backend/src/offboarding_flow/mcp/
├── __init__.py     # 模块说明
├── registry.py     # READ_TOOLS / WRITE_TOOLS 常量（共享给 middleware + tests + 文档）
├── server.py       # FastMCP 实例 + middleware 装配 + _maybe_register_write_tools
├── auth.py         # MagicLinkAuthMiddleware（复用 jwt_service.decode）
├── tools_read.py   # 7 个 read tools（默认开）
├── tools_write.py  # 4 个 write tools（默认禁，需 MCP_ALLOW_WRITE=true）
└── runner.py       # python -m offboarding_flow.mcp.runner stdio|http
```

### 鉴权链路

```
LLM client (Claude Desktop / Cursor / web agent)
    ↓ JSON-RPC over stdio 或 Streamable HTTP
[Authorization: Bearer <magic-link JWT>]   ← 仅 HTTP 模式有
    ↓
FastMCP MagicLinkAuthMiddleware.on_call_tool
    ↓ get_http_headers() → {} (stdio) or {"authorization": "Bearer ..."} (http)
    ├── stdio: set_state user_sub=local-stdio + user_role=admin（信任本地）
    └── http: decode_token(jwt) → set_state user_sub + user_role
    ↓
tool 函数 ctx.get_state('user_sub' / 'user_role')
    ↓
（write tools 额外）verify_actor_can_handle(node, sub, role) → ToolError if PermissionDenied
    ↓
复用业务 service（flow_service / node_service / handover_service）
    ↓
返回 dict（FastMCP 自动 serialize）
```

### 与项目其他约定的兼容

- **C-2（鉴权一致）**：复用 `auth/jwt_service.decode`，零新增 token 体系
- **C-3（双层状态分离）**：MCP tools 全部走 `app.*` 业务表（FlowRepository / NodeRepository / ActionRepository / handover_service.context），**不读 LangGraph checkpoint**
- **C-4（幂等）**：write tools 全部 wrap `node_service.submit_action`，已 upsert 安全
- **C-5（AI 边界）**：write tools 默认禁 + verify_actor_can_handle + AI disclaimer
- **CLAUDE.md §2.3（不 mock DB）**：tools_read 测试用 conftest db_session fixture（真 PG）

### 不实现项（明确 OUT OF SCOPE）

- `@mcp.prompt`（FastMCP 也支持 prompts）— Phase 9 候选
- `@mcp.resource`（资源 URI 暴露）— Phase 9 候选
- HTTP mode rate-limit（防 LLM 暴调用）— Phase 9 候选
- 更细粒度审计（per-tool 计数 → Grafana）— Phase 9 候选

## 参考实现

- 官方 quickstart: https://gofastmcp.com/getting-started
- TokenVerifier: https://gofastmcp.com/servers/auth/token-verification
- Claude Desktop 集成: https://gofastmcp.com/integrations/claude-desktop
- gelembjuk 的 JWT 鉴权 blog: https://gelembjuk.com/blog/post/authentication-remote-mcp-server-python/
