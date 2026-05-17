# Phase 08：IM/Doc 全抽象 + Huly 接入 + 流程 MCP 化 — Research

**Researched:** 2026-05-17
**Domain:** Protocol 抽象重构 / TypeScript sidecar 跨语言桥 / FastMCP server / Huly Platform 集成
**Confidence:** HIGH（架构 / 抽象 / MCP）· MEDIUM-HIGH（Huly SDK 已逐文件验证）· MEDIUM（Huly Forbidden 根因 — 已锁定 verifyAllowedServices 源码）

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions（来自 08-CONTEXT.md "范围 §2.1" + "设计约束 §6"）

- **8A 抽象重构（ABS-01..05）**：
  - ABS-01 — `IMListener` Protocol 定义 + 现有 `MattermostListener` 实现该 Protocol
  - ABS-02 — `mattermost_listener._handle_event` 行 175+ 提取为通用 `dispatch_message(sender, channel_id, channel_type, message, im_helpers)`
  - ABS-03 — `DocProvider` Protocol 补 `delete_collection / list_documents_in_collection / delete_document` 三个生命周期方法
  - ABS-04 — `IMProvider` Protocol 加 `register_command_listener(handler)` 反向订阅接口
  - ABS-05 — `bot_service.dispatch` 11 个 if/elif 重构为 HandlerRegistry 动态查表（参考 agent-builder im-bot 抽象草图）

- **8B Huly Provider（HULY-01..09）**：
  - HULY-01 — `scripts/pull_huly_images.sh` + `HULY_VERSION` env（已部 v0.7.423）
  - HULY-02 — docker-compose `huly-stack` profile（CockroachDB + Redpanda + ES + MinIO + 9 hardcoreeng 服务）+ `huly` profile（仅 sidecar）
  - HULY-03 — Node sidecar `backend/sidecars/huly-bridge/`（TypeScript + Express + `@hcengineering/api-client`）
  - HULY-04 — **service token 模式** = `generateToken(systemAccountUuid, undefined, { service: 'offboarding-bot' })`（已源码验证）
  - HULY-05 — 参考 `hcengineering/platform:services/telegram-bot/pod-telegram-bot` 把命令处理改成转 HTTP 到 backend
  - HULY-06 — `huly_doc_provider.py` + `huly_im_provider.py`（HTTP 调 sidecar）
  - HULY-07 — `huly_listener.py` 或路由 `POST /api/internal/huly/event`（接收 sidecar 反向推送）
  - HULY-08 — `scripts/seed_huly_users.py` — 业务 DB 13 个 user 一次性批量在 Huly 建 account
  - HULY-09 — `.env.example` 更新（HULY_* 占位变量）+ README §1 加 Huly 部署段

- **8C 流程 MCP 化（MCP-01..06）**：
  - MCP-01 — 使用 **FastMCP**（已通过决策；如不稳退路是官方 mcp SDK，但 FastMCP 已是 70% 生产 MCP 服务的底座）
  - MCP-02 — 7 read tools：`list_flows / get_flow / get_node_form / get_user_assignments / get_handover_docs / get_final_summary / get_meeting_summary`
  - MCP-03 — 4 write tools（默认禁用）：`advance_node / return_node / reject_node / submit_handover_doc`，需 `MCP_ALLOW_WRITE=true`
  - MCP-04 — MCP 鉴权 = Bearer token = magic-link JWT（sub=username 决定调用者身份，复用 `verify_actor_can_handle`）
  - MCP-05 — stdio mode（Claude Desktop） + HTTP/SSE mode（web agent） 双 transport
  - MCP-06 — Claude Desktop E2E 截图（`claude_desktop_config.json`）

- **设计约束（C-1..C-6）**：
  - C-1 — username 跨系统主键；Huly 用 `{username}@demo.local` 当 email（已锁）
  - C-2 — MCP 鉴权复用 magic-link JWT，不引入第二种 token 体系
  - C-3 — LangGraph checkpoint vs 业务 DB 双层分离；MCP tools 只读业务 DB，**不直接访问 checkpoint**
  - C-4 — MCP write tools upsert 安全，与 HTTP API 同质
  - C-5 — MCP write tools 默认禁用；即使开启也走 `verify_actor_can_handle` 角色闸门
  - C-6 — 8A/8B/8C 可并行开发（无写入冲突）

- **CLAUDE.md 全局**：中文注释 / commit message / 文档；并行优先；E2E 必须 browser-harness；集成测试禁止 mock DB；pre-commit hooks 不许 skip；凭证只走 .env

### Claude's Discretion（Claude 自主决定）

- HandlerRegistry 内部数据结构（dataclass vs Pydantic vs dict 注册表）
- `dispatch_message` 函数签名细节（参数顺序、是否传 `BotInvocationContext` 还是拆分）
- Node sidecar 内部组织：单文件 index.ts vs 模块化 src/{auth,im,doc,bridge}.ts
- FastMCP TokenVerifier 内部实现细节（自定义子类 vs middleware on_call_tool）
- nodes.yaml 的 schema 细节（CommandSpec.args 是否完全照搬 agent-builder 草图）
- Huly Document vs Wiki vs Card 选哪个做 handover doc 载体（见 §3.3.5）

### Deferred Ideas（OUT OF SCOPE — 见 CONTEXT.md §2.2）

- ❌ Huly 内置 tracker/project 直接做离职流程编排（流程引擎仍在 LangGraph，Huly 仅作 IM/Doc 数据源 + MCP 数据源）
- ❌ Huly 替代业务 DB（双库，不合并）
- ❌ MCP 暴露 AI 决策（advance/return/reject 仍必须人工最终确认）
- ❌ 多 workspace / 多 tenant 隔离（v1 单 workspace `laios`）
- ❌ 流程模板可视化编辑器（agent-builder 项目的事）
- ❌ Huly bot 命令重新写一套（`dispatch_message` 提取后 MM/Huly 共用同一套 handler，0 改动）
- ❌ DAG 拓扑也搬 YAML（深层是 Phase 9 的事，本 phase 只搬 `_NODE_META` 浅层元数据）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| **ABS-01** | `IMListener` Protocol 定义 + MattermostListener 实现 | §2.1 Protocol 设计；§2.2 现有 listener 拆解；§5.1 文件清单 |
| **ABS-02** | `dispatch_message` 函数提取 | §2.3 签名设计 + 4 步迁移流程；§4.1 单测策略 |
| **ABS-03** | `DocProvider` 补 3 个生命周期方法 | §2.4 接口增量；§3.3.5 Huly Document vs Wiki 决策 |
| **ABS-04** | `IMProvider` 加 `register_command_listener` | §2.5 反向订阅 hook |
| **ABS-05** | `bot_service.dispatch` HandlerRegistry 重构 | §2.6 HandlerRegistry 设计（4 层架构） |
| **HULY-01** | `pull_huly_images.sh` + `HULY_VERSION` | §3.1 镜像清单 14 个 + 一键脚本；§5.2 |
| **HULY-02** | docker-compose `huly-stack` + `huly` profiles | §3.2 双 profile 设计；§5.3 healthcheck |
| **HULY-03** | Node sidecar `backend/sidecars/huly-bridge/` | §3.3 sidecar 完整架构（auth/im/doc/listener 4 模块）；§5.4 |
| **HULY-04** | service token 模式（**已源码验证**） | §3.3.1 — generateToken(systemAccountUuid, undefined, {service:'offboarding-bot'}) |
| **HULY-05** | 参考 telegram-bot 把命令转 HTTP 到 backend | §3.3.4 反向 dispatch；§3.3.6 BRIDGE_TOKEN 鉴权 |
| **HULY-06** | huly_doc_provider.py + huly_im_provider.py | §3.4 Python provider 实现模板；§3.3.5 文档载体选型 |
| **HULY-07** | huly_listener.py / POST /api/internal/huly/event | §3.4.3 listener 模板；§3.3.4 反向推送 |
| **HULY-08** | seed_huly_users.py | §3.5 seed 脚本；§3.6 身份对齐（13 user × Huly account） |
| **HULY-09** | .env.example + README 更新 | §5.5 |
| **MCP-01** | FastMCP server | §4.1 FastMCP vs 官方 SDK 决策（HIGH 信心选 FastMCP 3.x） |
| **MCP-02** | 7 read tools | §4.3.1 read tools 完整签名 + 实现指引 |
| **MCP-03** | 4 write tools + MCP_ALLOW_WRITE | §4.3.2 write tools + 闸门设计 |
| **MCP-04** | Bearer JWT = magic-link JWT 鉴权 | §4.4 JWT verifier middleware 完整模式 |
| **MCP-05** | stdio + HTTP/SSE 双 transport | §4.5 transport 配置（Streamable HTTP 替代 SSE） |
| **MCP-06** | Claude Desktop E2E | §4.6 claude_desktop_config.json 模板 + browser-harness 截图 |
</phase_requirements>

## Summary

Phase 8 是一次**抽象 + 适配 + 暴露**三件套：8A 把单 IM 平台耦合的 `mattermost_listener` 重构成 Protocol + 通用 dispatcher；8B 引入 Huly 作为 IM/Doc 双能提供方（必须 Node sidecar，因为 Huly 只有 TS SDK）；8C 让 LLM 通过 MCP 直接读流程数据（write 默认禁）。三块代码无写入冲突，可并行。

研究的最高价值产出：**Huly service token 模式已通过逐文件源码验证**（`pod-telegram-bot/src/utils.ts` + `foundations/core/packages/token/src/token.ts` + `server/account/src/utils.ts`），直接锁定 `generateToken(systemAccountUuid, undefined, { service: 'offboarding-bot' })` + `SERVER_SECRET` 共享密钥。同样地，**createInviteLink autoJoin 在 Huly v0.7 只对 service='schedule' 开放**（源码 `verifyAllowedServices(['schedule'], extra)` 已截图）— 这就是之前 Forbidden 的根因，我们要么走 service='schedule' 伪装（不推荐，污染审计），要么 seed 阶段用 account-level token 调 `signUp/createInvite` 走非 autoJoin 路径（推荐）。

**Primary recommendation:** 8A 先行 1 周（抽象层是 8B/8C 的依赖）；8B/8C 并行 2 周；FastMCP 3.x 是 MCP-01 默认选；Node sidecar 用 `@hcengineering/api-client@0.7.423`（与已部署 Huly 同版本，workspace:* 版本号锁死）；service token 用 `@hcengineering/server-token` 的 `generateToken`。

## Standard Stack

### Core（Phase 8 直接依赖的库）

| 库 | 版本 | 用途 | 选用理由 |
|---|---|---|---|
| `fastmcp` | 3.3.1+ | MCP server 框架（Python） | 占 70% MCP 服务底座；decorator 注册 + 内置 Bearer/JWT 鉴权 + 双 transport；FastAPI 风格签名；Anthropic / Cloudflare 官方推荐 |
| `mcp` (Python SDK) | 1.x | FastMCP 内部依赖（保兜底） | FastMCP 已 bundle，无需直接 import |
| `@hcengineering/api-client` | `0.7.423` (workspace:^) | Huly TS 客户端 | 官方 SDK；与已部署 Huly 同版本（v0.7.423） |
| `@hcengineering/server-token` | `0.7.423` | service token 生成（generateToken） | 已源码验证；为非交互式 service-to-service 鉴权设计 |
| `@hcengineering/server-client` | `0.7.423` | account client（list integrations 等） | 与 server-token 配套；getAccountClient(token) |
| `@hcengineering/chunter` | `0.7.423` | Huly 聊天模型（Channel / DirectMessage / ChatMessage class refs） | DM/channel 操作必用 |
| `@hcengineering/contact` | `0.7.423` | Huly Person / Employee / SocialIdentity | 身份对齐必用 |
| `@hcengineering/document` | `0.7.423` | Huly Document / Teamspace | handover doc 选型核心 |
| `@hcengineering/core` | `0.7.423` | systemAccountUuid / AccountUuid / Ref types | 必用基础 |
| `express` | `^4.21.x` | sidecar HTTP server | 与 Huly 团队同栈（telegram-bot 用） |
| `tsx` | `^4.x` | TS 运行时（无需 tsc 编译步骤） | sidecar 单文件场景适用 |
| `pydantic` (Python) | 2.x（已在） | YAML schema + MCP tool params 校验 | 项目已用 |
| `pyyaml` | 6.x | nodes.yaml 加载 | 标准库无 yaml |

### Supporting（间接 / 兜底）

| 库 | 版本 | 用途 | 何时用 |
|---|---|---|---|
| `httpx` (Python) | 已在 0.28+ | Python → sidecar HTTP 调用 | 已在；huly_*_provider 内部用 |
| `tenacity` (Python) | 已在 | sidecar 启动重试 / connect retry | NFR-06 启动期不卡 |
| `python-jose` 或 `pyjwt` | 已在 `pyjwt` | MCP TokenVerifier 自定义 HS256 解码 | 复用 `auth/jwt_service.py` 既有 decode |
| `pydantic-yaml` (可选) | 1.x | YAML + Pydantic 一体化 | 仅当 nodes.yaml 复杂时；否则 `yaml.safe_load` + `Model.model_validate` 够用 |

### Alternatives Considered（决策记录）

| 替代标准 | 候选方案 | 决策 / 何时考虑替代 |
|---|---|---|
| **MCP framework** | 官方 `modelcontextprotocol/python-sdk` | FastMCP 3.x 是默认（API 简洁、生态成熟）；只有需要"完全自定义 transport / 协议"才回退官方 SDK |
| **Huly Bridge 语言** | 用 Rust（参考 `hcengineering/hulygram`） | TS 是默认（团队栈 + 官方 SDK 一致）；Rust 资源占用更优但维护成本高，本期不选 |
| **Huly Bridge 替代** | 第三方 `huly-mcp` server（`@firfi/huly-mcp` / `dearlordylord/huly-mcp`） | 不选 — 这些是给 LLM 用的 MCP 包装，不是给 Python backend 用的服务桥；我们要的是 backend → Huly 的同步 HTTP API |
| **Provider 切换机制** | 启动期 import-string 注册 | 选 `factory.py` switch + Settings.im_provider env（已有模式，加 case 即可） |
| **dispatch_message 风格** | class-based dispatcher（Strategy pattern） | 选独立 module-level async function（与 telegram-bot 风格一致，便于复用） |
| **HandlerRegistry 存储** | DB 表动态注册 | 选 in-memory dict + 模块 import（v1 不需要 hot reload） |
| **service token 替代** | 用真人 bot account（email/password） | **不选** — service token 是官方推荐，无密码维护成本，且 telegram-bot/ai-bot 都用此模式 |
| **MCP transport** | 旧 SSE | 选 **Streamable HTTP**（MCP 2025-11 spec 已 deprecate SSE，向后兼容） |
| **YAML loader** | tomli / json | 选 YAML（人类可读、可加注释）+ `yaml.safe_load`（防 RCE） |

**Installation（关键命令）：**

```bash
# Python 端 — backend/pyproject.toml 加
uv add fastmcp pyyaml
# pydantic / httpx / tenacity / pyjwt 已在

# Node sidecar — backend/sidecars/huly-bridge/package.json
npm init -y
npm install express tsx
npm install @hcengineering/api-client@0.7.423 \
            @hcengineering/server-token@0.7.423 \
            @hcengineering/server-client@0.7.423 \
            @hcengineering/chunter@0.7.423 \
            @hcengineering/contact@0.7.423 \
            @hcengineering/document@0.7.423 \
            @hcengineering/core@0.7.423
# 注意：Huly 是 monorepo workspace 协议；如果 npm 拉不到，需要从 Huly 镜像/tarball 提取
```

> **Huly 版本锁死警告**：`@hcengineering/*` 在官方 monorepo 用 `workspace:^0.7.423`，npm 公网未必提供独立包；如 npm 装失败，需用 `pnpm` + 从 `huly-selfhost` Dockerfile 提取 tarball（详见 §3.3.7 "依赖获取的兜底路径"）。

## Architecture Patterns

### Recommended Project Structure

```
backend/
├── src/offboarding_flow/
│   ├── im/                                # 🆕 8A IM 抽象层（新增目录）
│   │   ├── __init__.py
│   │   ├── protocol.py                    # IMListener Protocol（ABS-01）
│   │   ├── dispatcher.py                  # dispatch_message 通用函数（ABS-02）
│   │   ├── handler_registry.py            # HandlerRegistry（ABS-05）
│   │   └── context.py                     # BotInvocationContext 加 im_helpers
│   ├── providers/
│   │   ├── base.py                        # 🔄 ABS-03/04 加 3 + 1 个方法
│   │   ├── factory.py                     # 🔄 加 case "huly"
│   │   ├── mattermost_provider.py         # 🔄 实现新 Protocol 方法
│   │   ├── outline_provider.py            # 🔄 实现 delete_* / list_in_collection
│   │   ├── lark_provider.py               # 🔄 同上
│   │   ├── wecom_provider.py              # 🔄 同上（stub 即可）
│   │   ├── dingtalk_provider.py           # 🔄 同上（stub 即可）
│   │   ├── huly_im_provider.py            # 🆕 HULY-05
│   │   └── huly_doc_provider.py           # 🆕 HULY-06
│   ├── workers/
│   │   ├── mattermost_listener.py         # 🔄 实现 IMListener Protocol；改用 dispatch_message
│   │   └── huly_listener.py               # 🆕 HULY-07 — 接收 sidecar webhook
│   ├── api/
│   │   ├── internal_huly.py               # 🆕 HULY-07 — POST /api/internal/huly/event
│   │   └── mcp_router.py                  # 🆕 MCP-05 — 如选 HTTP transport 走 FastAPI
│   ├── mcp/                               # 🆕 8C MCP 目录
│   │   ├── __init__.py
│   │   ├── server.py                      # FastMCP 实例 + tools（MCP-01..03）
│   │   ├── auth.py                        # TokenVerifier / middleware（MCP-04）
│   │   ├── tools_read.py                  # 7 read tools
│   │   ├── tools_write.py                 # 4 write tools（默认禁）
│   │   └── runner.py                      # stdio / http 双 mode 启动入口（MCP-05）
│   └── services/
│       └── bot_service.py                 # 🔄 ABS-05 重构为 HandlerRegistry
├── sidecars/
│   └── huly-bridge/                       # 🆕 HULY-03 Node sidecar
│       ├── Dockerfile
│       ├── package.json
│       ├── tsconfig.json
│       └── src/
│           ├── index.ts                   # entrypoint：起 express + 连 Huly
│           ├── config.ts                  # env 读取
│           ├── auth.ts                    # service token + workspace token
│           ├── im.ts                      # send_dm / post_channel / ensure_member
│           ├── doc.ts                     # create_doc / create_space (teamspace)
│           ├── listener.ts                # subscribe chat → POST backend
│           └── types.ts                   # 共享类型
├── config/
│   └── nodes.yaml                         # 🆕 ABS-06 节点元数据（v1 浅层 — assignee/title/role）
└── scripts/
    ├── pull_huly_images.sh                # 🆕 HULY-01
    └── seed_huly_users.py                 # 🆕 HULY-08
```

### Pattern 1：Sidecar Bridge（跨语言 RPC）

**What:** Python backend 无法直接用 Huly TS SDK；起一个 Node 服务进程，对内暴露 HTTP API，对外用官方 SDK 连 Huly。Python 侧的 `huly_im_provider` / `huly_doc_provider` 只是 HTTP 客户端。

**When to use:** 目标平台只有非 Python SDK，且自建协议 reverse 风险太大（如 Huly 私有 Tx 协议）。

**Example:**
```typescript
// backend/sidecars/huly-bridge/src/index.ts
// Source: 综合自 platform/services/telegram-bot/pod-telegram-bot + huly.core/api-client README

import express from 'express'
import { connect } from '@hcengineering/api-client'
import { generateToken } from '@hcengineering/server-token'
import { systemAccountUuid } from '@hcengineering/core'
import { setMetadata } from '@hcengineering/platform'
import serverToken from '@hcengineering/server-token'

import { loadConfig } from './config.js'
import { mountImRoutes } from './im.js'
import { mountDocRoutes } from './doc.js'
import { startChatListener } from './listener.js'

async function main() {
  const config = loadConfig()
  // 关键：设置 SERVER_SECRET（必须与 Huly stack 同 secret），见 §3.3.1
  setMetadata(serverToken.metadata.Secret, config.SERVER_SECRET)
  setMetadata(serverToken.metadata.Service, 'offboarding-bot')

  // 拿一个 system service token（无需密码）
  const sysToken = generateToken(systemAccountUuid, undefined, { service: 'offboarding-bot' })

  // 用 sysToken connect 到目标 workspace（需要 admin 提前授权 bot account 加入 workspace）
  const client = await connect(config.HULY_URL, {
    token: sysToken,
    workspace: config.HULY_WORKSPACE
  })

  const app = express()
  app.use(express.json({ limit: '2mb' }))
  app.use(bridgeAuth(config.BRIDGE_TOKEN))   // 见 §3.3.6 鉴权 middleware

  mountImRoutes(app, client, config)         // /api/im/*
  mountDocRoutes(app, client, config)        // /api/doc/*

  await startChatListener(client, config)    // findAll(chunter.class.ChatMessage) 周期 poll，详见 §3.3.4

  const port = parseInt(config.PORT || '7777', 10)
  app.listen(port, () => console.log(`[huly-bridge] listening on :${port}`))
}

main().catch((e) => { console.error(e); process.exit(1) })
```

### Pattern 2：Protocol-based Pluggability（Python typing.Protocol）

**What:** 把 listener 行为抽成 Protocol（IMListener），具体实现按平台分；启动期按 env 选择实例。

**When to use:** 已有 1 个具体实现，要加第 2 / 3 个。

**Example:**
```python
# backend/src/offboarding_flow/im/protocol.py
from typing import Protocol, runtime_checkable, Awaitable, Callable

# dispatch_message 的 callable 签名（由通用 dispatcher 暴露给 listener 注入）
DispatchFn = Callable[..., Awaitable[None]]


@runtime_checkable
class IMListener(Protocol):
    """IM 平台被动监听通道抽象（WS / Webhook / HTTP poll 都可）。"""

    name: str   # "mattermost" | "huly" | "lark" | ...

    async def start(self) -> None:
        """启动监听（lifespan 期间一次性调用）。"""
        ...

    async def stop(self) -> None:
        """优雅停止。"""
        ...

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        """让 listener 在收到合法消息时调用统一 dispatch（ABS-04）。"""
        ...
```

### Pattern 3：通用 dispatch_message（消息层无关）

**What:** 把所有"IM 消息 → 业务命令"的逻辑收口到一个纯函数。

**When to use:** 多 IM 平台共用一套 bot 命令集合。

**Example:**
```python
# backend/src/offboarding_flow/im/dispatcher.py
from dataclasses import dataclass
from typing import Awaitable, Callable, Any

from offboarding_flow.services.bot_command_parser import BotCommandParseError, parse_command
from offboarding_flow.services.bot_intent_router import BotIntentRouter
from offboarding_flow.services.bot_service import (
    BotFlowNotFoundError, BotInvocationContext, BotPermissionError, BotService,
)


@dataclass(frozen=True)
class IMHelpers:
    """每个 IM 平台 listener 注入的回调集合（命令 handler 用它来"回复"）。

    通过 dataclass 而不是 dict，单测时 mock 更类型安全。
    """
    post_channel: Callable[[str, str], Awaitable[None]]    # (channel_id, markdown)
    send_dm: Callable[[str, str], Awaitable[None]]         # (username, markdown)
    ensure_in_channel: Callable[[str, str], Awaitable[None]] | None = None


async def dispatch_message(
    *,
    sender_username: str,
    user_id: str,
    channel_id: str,
    channel_type: str,         # 'D' | 'O' | 'P'（沿用 MM 约定，Huly 映射）
    message: str,
    im_helpers: IMHelpers,
    settings: Any,
    session_factory: Callable[[], Any],   # async context manager
) -> None:
    """统一消息分发。所有 IM listener（MM / Huly / Lark）都调这个函数。

    步骤：
    1. 跳过 bot 自己发的消息（由 listener 上游过滤，本函数不再校验）
    2. parse_command（白名单）
    3. 失败 → LLM intent router 兜底（与 mattermost_listener._handle_event 行 175+ 同逻辑）
    4. 查 sender_role
    5. 构造 BotInvocationContext + im_helpers
    6. BotService.dispatch
    7. 回写到 channel（通过 im_helpers.post_channel）
    """
    # 实现细节见 §2.3 4 步迁移流程
    ...
```

### Pattern 4：FastMCP + TokenVerifier 复用业务 JWT

**What:** MCP server 鉴权直接复用现有 magic-link JWT（`auth/jwt_service.py` 已有 HS256 + JWT_SECRET）。

**When to use:** 已有 JWT 体系，避免双 token 维护。

**Example:**
```python
# backend/src/offboarding_flow/mcp/auth.py
# Source: 综合 https://gofastmcp.com/servers/auth/token-verification +
#         https://gelembjuk.com/blog/post/authentication-remote-mcp-server-python/

from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.dependencies import get_http_headers
from fastmcp.exceptions import ToolError

from offboarding_flow.auth.jwt_service import decode_token   # 已存在 — 复用


class MagicLinkAuthMiddleware(Middleware):
    """复用 magic-link JWT 做 MCP Bearer 鉴权。

    1. stdio mode：跳过（trusted local context）
    2. HTTP mode：必须有 Authorization: Bearer <jwt>
    3. 解码后把 sub / role 注入 ctx.fastmcp_context state
    """

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        headers = get_http_headers()
        # stdio 模式 headers 为 {}，跳过鉴权（信任本地）
        if not headers:
            return await call_next(context)

        auth = headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            raise ToolError("MCP 请求缺少 Bearer token")
        token = auth.removeprefix("Bearer ").strip()
        try:
            payload = decode_token(token)   # 复用业务侧 JWT decode
        except Exception as e:
            raise ToolError(f"Bearer token 无效: {e}") from e

        # 注入 sub/role 让 tool 函数读
        context.fastmcp_context.set_state("user_sub", payload.sub)
        context.fastmcp_context.set_state("user_role", payload.role)
        return await call_next(context)
```

### Anti-Patterns to Avoid

- **❌ 自己 reverse Huly WebSocket Tx 协议**：私有协议升级 break 风险极高；用官方 TS SDK 经 sidecar 转一层是最稳路径。
- **❌ 给 bot 注册真人 email/password account**：每升级一次 Huly 都要重新登录拿 token；用 service token 一劳永逸。
- **❌ MCP tools 直接读 LangGraph checkpoint**：违反双层状态分离（C-3）；checkpoint 是引擎私有数据，pickle 格式不稳。MCP 只读 `app.*` 表。
- **❌ HandlerRegistry 用反射 `globals()` 找 handler**：会引入魔法，调试困难；用显式注册（`registry.register(name, handler)`）。
- **❌ sidecar 同 process 跑业务逻辑**：sidecar 只负责"传话"，业务逻辑在 backend；崩溃时业务不受影响。
- **❌ FastMCP HTTP 用旧 SSE transport**：MCP 2025-11 spec 已 deprecate SSE；用 `transport="streamable-http"`。
- **❌ Bridge 与 backend 之间不鉴权**：必须 `X-Bridge-Token` 共享 secret 验证（NFR-05）；否则任何能访问内网的进程都能伪造 IM 事件。
- **❌ Huly invite link 用 autoJoin=true + service='offboarding-bot'**：会 Forbidden（源码 `verifyAllowedServices(['schedule'], extra)`）；改用 seed 阶段直接 signUpJoin / accept invite，详见 §3.6.2。

## Don't Hand-Roll

| 问题 | 不要构建 | 使用现成方案 | 原因 |
|---|---|---|---|
| Huly WebSocket 客户端 | 自己 reverse Tx 协议 | `@hcengineering/api-client` | 协议是私有 + 升级频繁，自实现必崩 |
| Huly service token 签发 | 自己实现 jwt + secret | `@hcengineering/server-token` 的 `generateToken` | 与 Huly account service 必须用相同 secret + claims 结构 |
| MCP 协议本身 | 自实现 JSON-RPC stdio loop | FastMCP `@mcp.tool` decorator | 70% 生产 MCP 服务都用，stdio/HTTP transport 内置 |
| YAML 校验 | 自写 dict 校验 | Pydantic `model_validate` | 类型安全 + 错误信息友好 + 自动文档 |
| JWT decode | 自实现 HMAC verify | 项目已有 `auth.jwt_service.decode_token`（基于 pyjwt） | 已有；MCP 直接复用 |
| Docker healthcheck supervisor | 自写 cron-like 重启 | docker-compose `healthcheck:` + `restart: unless-stopped` | 内置 + 标准做法 |
| Huly Person/Account 创建 | 直接写 CockroachDB | Huly `signUp` + `selectWorkspace` + `createInvite` API | 必须经 Huly account service（多张关联表 + Tx 事件） |
| 命令解析正则 | 重写 | 已有 `bot_command_parser.py` | parser 已稳定，重构只换 dispatch |
| LLM intent router | 重写 | 已有 `bot_intent_router.py` + INTENT_ROUTER_PROMPT | 同上 |

**Key insight：** Huly 这套生态的核心是"用官方 SDK + 官方 service token 模式"。任何"绕一层"的做法（HTTP 暴破 / 假装真人 / reverse 协议）都会在 Huly 升级时崩。telegram-bot / ai-bot 这两个官方 reference 就是我们 sidecar 的模板。

## Common Pitfalls

### Pitfall 1：Huly autoJoin Forbidden（已 root-caused）

**What goes wrong:** 用 `createInviteLink({ autoJoin: true, ... })` 时返回 Forbidden，即使 token 是 admin / service token。

**Why it happens:** 源码 `server/account/src/operations.ts`：
```typescript
if (autoJoin === true) {
  verifyAllowedServices(['schedule'], extra)   // ← 写死只允许 schedule 服务
  // ...
}
```
而 `extra.service` 在 service token 里是 `'offboarding-bot'`，不在白名单 → 抛 Forbidden。

**How to avoid:**
- **方案 A（推荐）**：seed 阶段用 admin email/password 拿 workspace token，调 `signUpJoin(email, password, first, last, inviteId, workspace)` 直接为每个用户创建账号；inviteId 用 `createInvite(exp, emailMask, limit, role)`（不带 autoJoin）。
- **方案 B（不推荐）**：把 service 字段伪装成 `'schedule'`，会污染审计 + Huly 升级可能加更严校验。
- **方案 C**：13 个 user 量很小，**手动在 Huly UI 一次性 invite + 让用户首次登录设密码**；之后 bot 用 service token 操作不受影响。

**Warning signs:** sidecar 日志 `PlatformError: Forbidden`；invite link 返回 401/403。

### Pitfall 2：service token 必须与 Huly stack 同 SERVER_SECRET

**What goes wrong:** sidecar 调 generateToken 后 Huly account 服务 401。

**Why it happens:** `generateToken` 用 `getMetadata(serverPlugin.metadata.Secret)` 读 secret；签名密钥必须与 Huly account / transactor 容器的 `SERVER_SECRET` env 完全一致。

**How to avoid:**
- 在 docker-compose `huly-bridge` service 注入 `SERVER_SECRET: ${HULY_SERVER_SECRET}`（与 huly-stack 同变量）
- 启动期 `setMetadata(serverToken.metadata.Secret, config.SERVER_SECRET)` 必须先于任何 generateToken 调用
- 单测时 stub `setMetadata` 避免漏配

**Warning signs:** sidecar 调任何 `getAccountClient(serviceToken())` 方法都返回 `Token verification failed` / 401。

### Pitfall 3：mattermostautodriver / httpx 0.28+ 不兼容（已遇到）

**What goes wrong:** httpx 0.28+ 移除 `proxies` 参数，mattermostautodriver 2.0 还在传 → AsyncClient init 报错。

**Why it happens:** 已知历史问题。

**How to avoid:** `mattermost_listener.py` 已有 monkey-patch（行 32-40）；重构时**保留这段代码**或迁移到 `im/protocol.py` 顶部。

**Warning signs:** import 期 `TypeError: __init__() got an unexpected keyword argument 'proxies'`。

### Pitfall 4：节点函数幂等性 vs MCP write tools

**What goes wrong:** MCP `advance_node` 被 LLM 重复调用导致流程跳两步。

**Why it happens:** `interrupt()` 抛 GraphInterrupt 后节点函数会重跑，业务表已有幂等（UNIQUE 约束）但 MCP tool 调用本身没幂等键。

**How to avoid:**
- write tools 复用 `node_service.advance / return / reject`（这些方法已经走 upsert）
- 加 `idempotency_key` 参数（可选 UUID）— 写入 `action_logs.idempotency_key`，UNIQUE 约束去重
- tool 描述显式写"重复调用是幂等的，但建议传 idempotency_key"

**Warning signs:** action_logs 表同时间 2 条相同 actor + action_type；流程跳 2 步。

### Pitfall 5：sidecar 启动卡死 backend

**What goes wrong:** Huly 还没起来 / 网络抖动，sidecar 连不上 → `connect()` 一直 hang；backend startup 死等。

**Why it happens:** sidecar 不像 MM listener 嵌入 backend lifespan；sidecar 是独立 service，但 Python provider 启动 healthcheck 会同步等。

**How to avoid（NFR-06）：**
- sidecar 启动时用 retry（5 次 × 2s 指数退避），失败也启动 express server 监听并返回 503
- backend `huly_*_provider.__init__` 不主动 connect；首次调用时再 lazy 连
- docker-compose `healthcheck` 检查 sidecar `/healthz`（返回是否已连上 Huly），unhealthy 时 backend 不依赖
- `depends_on: huly-bridge` 改 `condition: service_started`（不等 healthy），sidecar 自己延迟 ready

**Warning signs:** `docker compose up` 卡在 "Waiting for huly-bridge to be healthy"。

### Pitfall 6：Huly 一条消息触发死循环

**What goes wrong:** bot 发的消息又被 sidecar 的 subscribe 捕获 → POST 给 backend → 又触发 bot 回复 → 无限循环。

**Why it happens:** Huly 没有 MM 那种 `user_id == bot_user_id` 简单过滤。

**How to avoid:**
- sidecar 在 subscribe 处拿到 `msg.createdBy`（PersonId）与本地缓存的 `botSocialId` 比较，相等则 skip
- 二次保险：消息里包含 `🤖` / 我们已知的回复前缀，跳过
- 三次保险：rate-limit per (sender_username, 5s) 1 条

**Warning signs:** Huly DM 里 bot 自言自语滚屏；CPU 飙高。

### Pitfall 7：FastMCP HTTP 模式 stateless_http 选错导致 token state 丢

**What goes wrong:** Bearer 鉴权 middleware set_state 后下一次 tool 调用读不到。

**Why it happens:** Streamable HTTP 推荐 `stateless_http=True`（生产可扩展），但 stateless 模式 ctx state 是 per-request 的；middleware on_call_tool 在同一请求里 set_state → 同 tool 函数能读，OK；如果设计成"中间件认证 → 下次调用读"则会丢。

**How to avoid:**
- middleware 在 `on_call_tool` 内 set_state，**同一调用链**里的 tool 函数立即读，没问题
- 不要跨请求依赖 state；每次都从 Authorization header 重新 decode

**Warning signs:** "user_sub not in state" 错误；多 client 串扰。

### Pitfall 8：MCP write tools 鉴权绕过

**What goes wrong:** `MCP_ALLOW_WRITE=false` 但 LLM 还是能调 write tool（因为只是描述不暴露，没有 server-side 拒绝）。

**Why it happens:** FastMCP 默认所有 `@mcp.tool` 都注册；只在描述里写"禁用"不是真的禁用。

**How to avoid:**
- 启动期判 env：`if not settings.mcp_allow_write: 不注册 write tools`（最干净）
- 或 middleware on_call_tool 里 `if tool_name in WRITE_TOOLS and not allow_write: raise ToolError(...)`
- write tool 内部再做一道 `verify_actor_can_handle(node, sub, role)` 闸门（已有 helper）

**Warning signs:** demo 时切 `MCP_ALLOW_WRITE=false` 后 Claude 仍能 advance_node。

### Pitfall 9：Huly Document / Wiki / Card 选型混乱

**What goes wrong:** handover doc 写到 `chunter` 或 `card` 里而不是 `document.Document`，UI 看不到 Wiki 树。

**Why it happens:** Huly 有 4 个文档相关 module — `document`（Wiki 文档 / Teamspace 树）、`controlled-documents`（受控文档 / 审批流）、`board`（看板卡片）、`card`（实体卡片）。handover doc 是"按员工分文件夹的多份 markdown" → 用 `document.class.Document` + `document.class.Teamspace`。

**How to avoid:**
- 用 `documentPlugin.class.Teamspace`（每员工一个 Teamspace = `离职 · {username}`）
- 用 `documentPlugin.class.Document`（每节点一份）+ `rank` + `parent` 控制树形
- 参考 `dearlordylord/huly-mcp:src/huly/operations/documents.ts` 的 `findTeamspace` / `createDocument` 实现

**Warning signs:** Huly UI Wiki 看不到内容；只在 "All Documents" 搜索能看到。

## Code Examples

### 8A — IMListener Protocol + MattermostListener 适配（ABS-01）

```python
# backend/src/offboarding_flow/im/protocol.py
"""IM listener 抽象（ABS-01）。

实现要求：
- 实现 start() / stop() / register_command_listener(dispatch)
- 内部收到消息后调 self._dispatch（dispatch_message 通用函数）
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable, Awaitable, Callable

DispatchFn = Callable[..., Awaitable[None]]


@runtime_checkable
class IMListener(Protocol):
    name: str

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def register_command_listener(self, dispatch: DispatchFn) -> None: ...
```

适配现有 `MattermostListener`：

```python
# 在 mattermost_listener.py 顶部加 import
from offboarding_flow.im.protocol import IMListener
from offboarding_flow.im.dispatcher import dispatch_message, IMHelpers


class MattermostListener:   # 已有
    name = "mattermost"     # 🆕 满足 Protocol

    def __init__(self, settings: Settings) -> None:
        # ...已有
        self._dispatch: DispatchFn | None = None

    def register_command_listener(self, dispatch):   # 🆕 ABS-04
        self._dispatch = dispatch

    async def _handle_event(self, event_str):
        # ...保留 WS 解码 / 触发条件检查（行 129-173 不变）

        # 行 175+ 原 dispatch 逻辑替换为：
        helpers = IMHelpers(
            post_channel=self._post_reply,
            send_dm=self._send_dm_by_username,
            ensure_in_channel=self._ensure_user_in_channel,
        )
        if self._dispatch is not None:
            await self._dispatch(
                sender_username=sender_name,
                user_id=post_user_id,
                channel_id=channel_id,
                channel_type=channel_type,
                message=message,
                im_helpers=helpers,
                settings=self.settings,
                session_factory=new_session,
            )
```

启动期注册：

```python
# main.py lifespan
listener: IMListener
if settings.im_provider == "mattermost":
    listener = MattermostListener(settings)
elif settings.im_provider == "huly":
    listener = HulyListener(settings)
listener.register_command_listener(dispatch_message)
await listener.start()
```

### 8A — HandlerRegistry 重构 bot_service.dispatch（ABS-05）

```python
# backend/src/offboarding_flow/im/handler_registry.py
"""HandlerRegistry — bot 命令分发表（ABS-05）。

替代 bot_service.dispatch 11 个 if/elif 分支。
"""
from dataclasses import dataclass
from typing import Awaitable, Callable, Any

HandlerFn = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class HandlerSpec:
    name: str
    handler: HandlerFn
    description: str
    allowed_roles: frozenset[str] = frozenset()   # 空 set = 所有人；非空 = 白名单


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, HandlerSpec] = {}

    def register(self, spec: HandlerSpec) -> None:
        self._handlers[spec.name] = spec

    def get(self, name: str) -> HandlerSpec | None:
        return self._handlers.get(name)

    def all(self) -> list[HandlerSpec]:
        return list(self._handlers.values())


# bot_service.py 顶部初始化：
_REGISTRY = HandlerRegistry()

def _setup_registry():
    _REGISTRY.register(HandlerSpec("help", _handle_help, "命令帮助"))
    _REGISTRY.register(HandlerSpec("start", _handle_start, "启动离职流程",
                                   allowed_roles=frozenset({"hr","hr_admin","admin"})))
    _REGISTRY.register(HandlerSpec("status", _handle_status, "查询流程状态"))
    # ... 11 个 handler
_setup_registry()


# BotService.dispatch 变成 3 行：
async def dispatch(self, cmd: BotCommand, ctx: BotInvocationContext) -> str:
    spec = _REGISTRY.get(cmd.name)
    if spec is None:
        raise ValueError(f"未知命令：{cmd.name}")
    if spec.allowed_roles and ctx.user_role not in spec.allowed_roles:
        raise BotPermissionError(f"权限不足：{cmd.name} 仅 {spec.allowed_roles} 可用")
    return await spec.handler(cmd, ctx, self)
```

### 8A — `_NODE_META` → YAML（ABS-06）

```yaml
# config/nodes.yaml
# 11 节点元数据（assignee_role / title）— 业务表 node_states 写入时引用
nodes:
  - idx: 1
    name: apply
    title: 离职申请
    assignee_role: applicant
  - idx: 2
    name: manager_review
    title: 上级审批
    assignee_role: manager
  # ... 11 个
```

```python
# backend/src/offboarding_flow/config/node_meta.py
import yaml
from pathlib import Path
from pydantic import BaseModel

class NodeMeta(BaseModel):
    idx: int
    name: str
    title: str
    assignee_role: str

class NodesConfig(BaseModel):
    nodes: list[NodeMeta]

def load_nodes() -> list[NodeMeta]:
    path = Path(__file__).parents[3] / "config" / "nodes.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return NodesConfig.model_validate(data).nodes
```

### 8B — Node sidecar 完整骨架（HULY-03/04）

`backend/sidecars/huly-bridge/src/auth.ts`：

```typescript
// Source: 直接源码验证 platform/services/telegram-bot/pod-telegram-bot/src/utils.ts + start.ts
import { generateToken } from '@hcengineering/server-token'
import { systemAccountUuid } from '@hcengineering/core'
import { setMetadata } from '@hcengineering/platform'
import serverToken from '@hcengineering/server-token'
import serverClient from '@hcengineering/server-client'

export function initAuth(serverSecret: string, accountsUrl: string) {
  setMetadata(serverToken.metadata.Secret, serverSecret)
  setMetadata(serverToken.metadata.Service, 'offboarding-bot')
  setMetadata(serverClient.metadata.Endpoint, accountsUrl)
  setMetadata(serverClient.metadata.UserAgent, 'offboarding-bot/1.0')
}

export function serviceToken(): string {
  // 完全照搬 telegram-bot 的 serviceToken() 实现
  return generateToken(systemAccountUuid, undefined, { service: 'offboarding-bot' })
}
```

`backend/sidecars/huly-bridge/src/im.ts`（DM 与 channel 发送）：

```typescript
// Source: 综合 dearlordylord/huly-mcp:src/huly/operations/channels.ts +
//         hcengineering/platform:services/ai-bot/pod-ai-bot/src/utils/platform.ts
import { Router } from 'express'
import type { PlatformClient } from '@hcengineering/api-client'
import core, { generateId, type AccountUuid, type Ref } from '@hcengineering/core'
import chunter, { type ChatMessage, type DirectMessage } from '@hcengineering/chunter'
import contact from '@hcengineering/contact'

export function mountImRoutes(router: Router, client: PlatformClient, botAccount: AccountUuid) {
  // POST /api/im/send_dm  { to_username, markdown }
  router.post('/api/im/send_dm', async (req, res) => {
    const { to_username, markdown } = req.body
    // 1. username → AccountUuid（通过 SocialIdentity / Employee）
    const targetAccount = await resolveAccountByUsername(client, to_username)
    if (!targetAccount) return res.status(404).json({ error: 'user not found' })

    // 2. 查或建 DM space — 参考 ai-bot getDirect()
    let dm = (await client.findAll(chunter.class.DirectMessage, { members: botAccount }))
      .find((d) => d.members.length === 2 && d.members.includes(targetAccount))

    let dmId: Ref<DirectMessage>
    if (dm === undefined) {
      dmId = await client.createDoc(chunter.class.DirectMessage, core.space.Space, {
        name: '', description: '', private: true, archived: false,
        members: [botAccount, targetAccount],
      })
    } else {
      dmId = dm._id
    }

    // 3. 发消息（addCollection 模式，参考 huly-mcp:channels.ts sendChannelMessage）
    const msgId = generateId<ChatMessage>()
    await client.addCollection(
      chunter.class.ChatMessage,
      dmId, dmId, chunter.class.DirectMessage, 'messages',
      { message: markdownToMarkup(markdown), attachments: 0 },
      msgId,
    )
    res.json({ ok: true, message_id: msgId, dm_id: dmId })
  })

  // POST /api/im/post_channel  { channel_id, markdown }
  router.post('/api/im/post_channel', async (req, res) => { /* 类似 — addCollection ChatMessage to Channel */ })
}
```

`backend/sidecars/huly-bridge/src/listener.ts`（反向订阅）：

```typescript
// Source: 综合 huly.core/api-client + telegram-bot worker pattern
// Huly 没有"内置 chat webhook"，只能 poll findAll 或用 client.query (txOps live subscribe)
import type { PlatformClient } from '@hcengineering/api-client'
import chunter, { type ChatMessage } from '@hcengineering/chunter'
import { SortingOrder } from '@hcengineering/core'

export async function startChatListener(
  client: PlatformClient,
  config: { BACKEND_URL: string; BRIDGE_TOKEN: string; botAccountUuid: string },
) {
  let lastSeen = Date.now()
  setInterval(async () => {
    // poll：找比 lastSeen 新的消息（v1 实现，简单可靠）
    // v2 优化：用 client.query (live) 订阅 — 但 PlatformClient 接口未公开 query；
    //         可参考 platform/foundations/core/packages/client 自行 wrap
    const msgs = await client.findAll(
      chunter.class.ChatMessage,
      { createdOn: { $gt: lastSeen } },
      { sort: { createdOn: SortingOrder.Ascending }, limit: 100 },
    )
    for (const m of msgs) {
      if (m.modifiedBy === config.botAccountUuid) continue   // 跳自己防死循环
      lastSeen = Math.max(lastSeen, m.createdOn)
      // POST 给 backend
      await fetch(`${config.BACKEND_URL}/api/internal/huly/event`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Bridge-Token': config.BRIDGE_TOKEN },
        body: JSON.stringify({
          sender_account: m.modifiedBy,
          channel_id: m.attachedTo,
          attached_to_class: m.attachedToClass,   // 'chunter:class:DirectMessage' or '...Channel'
          message: m.message,
          ts: m.createdOn,
        }),
      })
    }
  }, 2000)
}
```

### 8B — Python provider（HULY-06）

```python
# backend/src/offboarding_flow/providers/huly_im_provider.py
import httpx
from offboarding_flow.providers.base import IMProvider, UserInfo, ProviderError


class HulyIMProvider:
    """HTTP 调 huly-bridge 实现 IMProvider Protocol。"""
    name = "huly"

    def __init__(self, settings):
        self._url = settings.huly_bridge_url.rstrip("/")
        self._token = settings.huly_bridge_token
        self._client = httpx.AsyncClient(
            base_url=self._url,
            headers={"X-Bridge-Token": self._token},
            timeout=15.0,
        )

    async def send_dm(self, username: str, markdown: str) -> None:
        try:
            r = await self._client.post("/api/im/send_dm",
                                         json={"to_username": username, "markdown": markdown})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ProviderError(f"huly send_dm 失败：{e}") from e

    async def post_to_channel(self, channel_id: str, markdown: str) -> None: ...
    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None: ...
    async def list_team_users(self) -> list[UserInfo]: ...
    async def resolve_username(self, username: str) -> UserInfo | None: ...
```

### 8C — FastMCP server 完整骨架（MCP-01..05）

```python
# backend/src/offboarding_flow/mcp/server.py
# Source: https://gofastmcp.com/getting-started + https://gofastmcp.com/servers/auth/token-verification
from fastmcp import FastMCP, Context
from offboarding_flow.config import get_settings
from offboarding_flow.mcp.auth import MagicLinkAuthMiddleware

settings = get_settings()
mcp = FastMCP("offboarding-flow")
mcp.add_middleware(MagicLinkAuthMiddleware())

# ============ read tools（默认全开）============

@mcp.tool
async def list_flows(filter: str = "active", ctx: Context = None) -> dict:
    """列出所有离职流程（active / completed / stuck）。"""
    from offboarding_flow.state_store.session import new_session
    from sqlalchemy import select
    from offboarding_flow.state_store.models import FlowInstance
    async with new_session() as s:
        rows = (await s.execute(select(FlowInstance).limit(50))).scalars().all()
        return {"flows": [{"id": str(f.id), "employee_id": f.employee_id, "status": f.status} for f in rows]}


@mcp.tool
async def get_flow(flow_id: str, ctx: Context = None) -> dict:
    """获取指定流程的 DAG 状态 + 节点清单 + 进度。"""
    # 复用 FlowService.list_nodes
    ...


@mcp.tool
async def get_node_form(flow_id: str, node_id: str, ctx: Context = None) -> dict:
    """获取某节点的表单（说明 / payload / 当前 result_text / 当前 assignee）。"""
    ...


@mcp.tool
async def get_user_assignments(username: str, ctx: Context = None) -> dict:
    """列出某用户当前待处理的节点（跨流程）。"""
    ...


@mcp.tool
async def get_handover_docs(flow_id: str, ctx: Context = None) -> dict:
    """列出某流程已生成的 handover docs（URL + title）。"""
    ...


@mcp.tool
async def get_final_summary(flow_id: str, ctx: Context = None) -> dict:
    """获取某流程的最终聚合 markdown（applicant_final_confirm 节点的 glm_summary）。"""
    ...


@mcp.tool
async def get_meeting_summary(meeting_id: str, ctx: Context = None) -> dict:
    """获取某会议纪要的 AI 分析（tasks/blockers/decisions）。"""
    ...


# ============ write tools（默认禁用）============

if settings.mcp_allow_write:
    @mcp.tool
    async def advance_node(flow_id: str, node_id: str, result_text: str,
                            idempotency_key: str | None = None, ctx: Context = None) -> dict:
        """推进某节点（必须是该节点的 assignee）。

        ⚠️ 写操作 — 会改变流程状态。建议传 idempotency_key（UUID）防重复推进。
        """
        sub = ctx.get_state("user_sub")
        role = ctx.get_state("user_role")
        # 复用 node_service.advance + verify_actor_can_handle
        ...

    @mcp.tool
    async def return_node(...): ...
    @mcp.tool
    async def reject_node(...): ...
    @mcp.tool
    async def submit_handover_doc(...): ...


# ============ entry point — stdio / http 双 mode ============

def run_stdio():
    mcp.run()   # 默认 stdio

def run_http():
    mcp.run(transport="streamable-http", host="0.0.0.0", port=settings.mcp_http_port,
            path="/mcp", stateless_http=True)
```

`backend/src/offboarding_flow/mcp/runner.py`：

```python
"""MCP entry：python -m offboarding_flow.mcp.runner stdio|http"""
import sys
from offboarding_flow.mcp.server import run_stdio, run_http

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    {"stdio": run_stdio, "http": run_http}[mode]()
```

### 8C — Claude Desktop 配置（MCP-06）

```json
// ~/Library/Application Support/Claude/claude_desktop_config.json
{
  "mcpServers": {
    "offboarding-flow": {
      "command": "uv",
      "args": [
        "run", "--project", "/Users/admin/ai/resume/interview/liuxin/hr/backend",
        "python", "-m", "offboarding_flow.mcp.runner", "stdio"
      ],
      "env": {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5433",
        "JWT_SECRET": "<from .env>",
        "MCP_ALLOW_WRITE": "false"
      }
    }
  }
}
```

### 8B — docker-compose huly-bridge service（HULY-02）

```yaml
# docker-compose.yml 末尾追加
services:
  huly-bridge:
    profiles: ["huly"]
    build:
      context: ./backend/sidecars/huly-bridge
      dockerfile: Dockerfile
    container_name: offboarding-huly-bridge
    environment:
      HULY_URL: ${HULY_URL}                              # http://192.168.2.44:8087
      HULY_ACCOUNTS_URL: ${HULY_ACCOUNTS_URL}            # http://192.168.2.44:8087/_accounts
      HULY_WORKSPACE: ${HULY_WORKSPACE}                  # laios
      SERVER_SECRET: ${HULY_SERVER_SECRET}               # ← 与 huly-stack SERVER_SECRET 同
      BACKEND_URL: http://backend:8000
      BRIDGE_TOKEN: ${HULY_BRIDGE_TOKEN}                 # ↔ backend X-Bridge-Token
      PORT: "7777"
    ports:
      - "7777:7777"
    networks: [offboarding-net]
    depends_on:
      backend:
        condition: service_started
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:7777/healthz"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 30s
```

## State of the Art

| 旧做法 | 当前做法 | 变更点 / 影响 |
|---|---|---|
| MCP 协议用 SSE transport | **Streamable HTTP**（MCP 2025-11 spec） | SSE 已 deprecated；新项目用 streamable-http；FastMCP 3.x 默认支持 |
| MCP server 自己实现 JSON-RPC | **FastMCP 3.x**（decorator API） | 占 70% MCP 生产服务底座；Anthropic 推荐 |
| Huly bot 用真人 email/password | **service token**（`generateToken(systemAccountUuid, undefined, {service: '...'})`） | telegram-bot / ai-bot 都用；无密码维护 |
| Python listener 嵌入 backend lifespan | sidecar 模式（**当 SDK 只有 TS 时**） | Huly TS SDK 是唯一可靠路径；Rust SDK (`hulyrs`) 是次选 |
| `_NODE_META` 硬编码 in code | **YAML 配置 + Pydantic 校验** | 改节点元数据不需要重启代码（v1 加载一次；v2 支持热加载） |
| listener 内 if/elif 分发 | **HandlerRegistry**（in-memory dict） | 新增命令只需 `_REGISTRY.register(...)` 一行 |
| MCP 鉴权用 OAuth2 完整流程 | 复用 magic-link JWT Bearer（HS256） | LLM 客户端拿 token 简单；与现有体系一致 |

**Deprecated/outdated:**
- **MCP SSE-only transport**：MCP 2025-11 spec 起改 Streamable HTTP；FastMCP 3.x 仅文档保留 SSE 兼容描述。
- **手写 11 个 if/elif dispatch**：HandlerRegistry pattern 已是标准。
- **Huly v0.6 镜像（v0.6.500 系列）**：已部 v0.7.423，固定该版本（v0.7 后 Account 服务 endpoint 改为 `_accounts` RPC 风格）。

## Open Questions

### 1. Huly v0.7 `_accounts` RPC 与旧 `/api/v1/*` 是否完全等价？

- **What we know:** v0.7.423 暴露 `POST /_accounts`，body 是 `{method, params}` RPC 风格；旧 v0.6 是 REST 风格 `/api/v1/login` 等
- **What's unclear:** 旧文档（如 huly.core README）展示 REST API；v0.7 的 RPC endpoint 在文档中没显式列出 method 清单
- **Recommendation:** 用 `@hcengineering/account-client` 0.7.423 包（其内部已封装 RPC），不直接 fetch；客户端方法名（login/signUp/selectWorkspace/createInvite/createInviteLink/listIntegrations 等）对应 RPC method 名

### 2. Huly chat message 实时订阅 — 是否能用 `client.query()` live 而不是 poll？

- **What we know:** `dearlordylord/huly-mcp` 和 `@hcengineering/api-client` 的 README 都没明确暴露 `query()` live subscribe；只有 `findAll` 一次性查询
- **What's unclear:** Huly 自家 UI 是用 `client.query()` 做实时 reactive（plugins/chunter-resources 里有），但 `PlatformClient` 接口（types.ts FindOperations/DocOperations）没有 query 方法
- **Recommendation:** v1 用 **2s poll**（与 telegram-bot 处理 outgoing 通知的间隔一致），简单可靠；v2 优化时探查 `foundations/core/packages/client` 的 `Client.tx` 事件流，自己 wrap subscribe

### 3. Huly DocumentSpace（Teamspace） vs Wiki vs Card：handover doc 用哪个？

- **What we know:** `dearlordylord/huly-mcp:src/huly/operations/documents.ts` 用 `documentPlugin.class.Teamspace + Document`，是 Wiki 树结构
- **What's unclear:** Huly v0.7 是否还保留 v0.6 那个独立 "Wiki" module（chunter 之外）？v0.7 似乎统一到 `document` 了
- **Recommendation:** 用 `document.class.Teamspace`（一个员工一个 Teamspace = "离职 · {username}"） + `document.class.Document`（每节点一份），与 `huly-mcp` 实现对齐；如果 v0.7 Wiki 还是独立的可改 `wiki.class.WikiPage`

### 4. seed_huly_users 完整流程 — admin/system token 哪个能行？

- **What we know:** signUp / signUpJoin / createInvite 需要 admin role token；service token 在 server/account/src/operations.ts 大多数操作里被 `verifyAllowedServices` 限定
- **What's unclear:** v0.7 `signUp` 是否对 service='offboarding-bot' 开放？
- **Recommendation:** seed_huly_users.py **用 admin email/password token**（一次性脚本）+ `signUpJoin` 走 invite 路径；运行时业务 bot 用 service token（只读 + 发消息 + 建文档不涉及 invite）

### 5. dispatch_message 是否需要支持 Lark / WeCom listener？

- **What we know:** CONTEXT.md 8A 范围明确 ABS-01 是"加 Listener Protocol"，但 Lark / WeCom 现状是只有 Provider 没有 Listener
- **What's unclear:** Phase 8 是否要顺带加 Lark/WeCom Listener
- **Recommendation:** **不加**（避免范围爆炸）；Protocol 设计要支持，但本 Phase 只实现 MM + Huly 两个 listener；Lark / WeCom 留 Phase 9（CH-01/02 已在 v2 requirements）

### 6. MCP server 进程跟谁一起部署？

- **What we know:** stdio mode 必须随 Claude Desktop subprocess 启动；HTTP mode 可独立容器
- **What's unclear:** docker-compose 是否要加 `mcp-http` service？还是只在 backend 内 multiplex（同 ASGI app 加一个 router）？
- **Recommendation:**
  - **stdio mode**：不部署到容器，本机 `uv run` 即可（Claude Desktop subprocess）
  - **HTTP mode**：v1 在 backend FastAPI app 内 mount `mcp.http_app()` 到 `/mcp/*`（FastMCP 支持 mount 到 FastAPI），避免多一个进程
  - 这样 docker-compose 不增容器，nginx 反代多加一段 `location /mcp/`

## Sources

### Primary（HIGH 信心 — 官方源码 / 官方文档）

- **`hcengineering/platform:services/telegram-bot/pod-telegram-bot/src/account.ts`** — service token 使用模式（`getAccountClient(generateToken(...))`）— 已 `gh api` 直接读源码
- **`hcengineering/platform:services/telegram-bot/pod-telegram-bot/src/utils.ts`** — `serviceToken()` 函数定义 — 已直接读源码
- **`hcengineering/platform:services/telegram-bot/pod-telegram-bot/src/start.ts`** — `setMetadata(serverToken.metadata.Secret, ...)` 启动期初始化 — 已直接读源码
- **`hcengineering/platform:foundations/core/packages/token/src/token.ts`** — `generateToken` 完整签名（accountUuid, workspaceUuid, extra, secret, options） — 已直接读源码
- **`hcengineering/platform:server/account/src/operations.ts`** — `createInviteLink` 含 `verifyAllowedServices(['schedule'], extra)`（**Forbidden 根因**） — 已直接读源码
- **`hcengineering/platform:server/account/src/utils.ts`** — `verifyAllowedServices` / `verifyAllowedRole` 实现 — 已直接读源码
- **`hcengineering/platform:foundations/core/packages/api-client/src/{client,types,utils}.ts`** — `connect()` / `WorkspaceToken` / `PlatformClient` 接口 — 已直接读源码
- **`hcengineering/platform:foundations/core/packages/account-client/src/client.ts`** — `createInviteLink(email, role, autoJoin, ...)` 签名 — 已直接读源码
- **`hcengineering/platform:services/ai-bot/pod-ai-bot/src/utils/platform.ts`** — `getDirect(client, account, aiPerson?)` 创建 bot ↔ user DM 的标准模式（**canonical pattern**） — 已直接读源码
- **[huly.core api-client README](https://github.com/hcengineering/huly.core/blob/main/packages/api-client/README.md)** — connect / findOne / findAll / createDoc / updateDoc / removeDoc 全量示例
- **`dearlordylord/huly-mcp:src/huly/operations/{channels,direct-messages,documents,channels-messages}.ts`** — 真实生产实现（MIT 许可，可参考） — 已直接读源码
- **[FastMCP gofastmcp.com Bearer/Token Verification](https://gofastmcp.com/servers/auth/token-verification)** — TokenVerifier / BearerAuthProvider 模式
- **[FastMCP Upgrade Guide](https://gofastmcp.com/getting-started/upgrading/from-mcp-sdk)** — 3.x transport 配置（`mcp.run(transport="streamable-http", host=..., port=...)`）
- **[FastMCP Claude Desktop Integration](https://gofastmcp.com/integrations/claude-desktop)** — `claude_desktop_config.json` 模板（uv run pattern）
- **[Cloudflare blog — Streamable HTTP MCP](https://blog.cloudflare.com/streamable-http-mcp-servers-python/)** — SSE → Streamable HTTP transport 演进

### Secondary（MEDIUM 信心 — 验证过的社区文档）

- **[FastMCP GitHub jlowin/fastmcp](https://github.com/jlowin/fastmcp)** — v3.3.1 (2026-05-15)，`uv pip install fastmcp`
- **[Roman gelembjuk.com — Authentication in Remote MCP Server](https://gelembjuk.com/blog/post/authentication-remote-mcp-server-python/)** — UserAuthMiddleware on_call_tool 完整模式
- **[Huly docs Sending Messages](https://docs.huly.io/communication/sending-messages/)** — chat 概念
- **[Sarah Glasmacher — YAML Pydantic validation](https://www.sarahglasmacher.com/how-to-validate-config-yaml-pydantic/)** — yaml.safe_load + model_validate 标准模式
- **[Huly hulygram repo](https://github.com/hcengineering/hulygram)** — Rust 实现的 telegram interface（备选语言栈参考）

### Tertiary（LOW 信心 — 仅作辅助，需自验）

- **[FastMCP 2.0 vs python-sdk discussion](https://github.com/PrefectHQ/fastmcp/discussions/2557)** — 框架选型背景
- **[Comparing MCP Server Frameworks (Medium)](https://medium.com/@FrankGoortani/comparing-model-context-protocol-mcp-server-frameworks-03df586118fd)** — 对比文章（已交叉验证关键结论）
- **[Configure Bearer auth in MCP server](https://mcp-auth.dev/docs/configure-server/bearer-auth)** — Bearer 配置背景

## Metadata

**Confidence breakdown:**
- Standard stack（FastMCP / api-client / express）: **HIGH** — 多渠道交叉验证 + 直接源码
- Architecture（sidecar / dispatch_message / HandlerRegistry / FastMCP middleware）: **HIGH** — 源码 + 现成参考实现（telegram-bot / ai-bot / huly-mcp）
- Pitfalls（autoJoin Forbidden / SERVER_SECRET / DM 死循环 / sidecar 启动卡死）: **HIGH** — Forbidden 根因已源码直接定位
- Code examples: **HIGH** — 所有 TS 示例都综合自真实生产源码（已贴源码注释）
- Huly Document/Wiki/Card 选型: **MEDIUM** — v0.7 module 命名可能与文档样例略有出入，需 POC 验证
- Huly chat live subscribe（vs poll）: **MEDIUM** — 已确认 v1 走 poll 路径稳；live 路径待 v2 探查

**Research date:** 2026-05-17
**Valid until:** 2026-08-17（FastMCP 3.x + Huly v0.7.423 都是稳定线，3 个月内框架不太可能 break）
**Phase requirements coverage:** 20/20（ABS-01..05 + HULY-01..09 + MCP-01..06）
