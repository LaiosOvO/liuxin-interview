# PRD — Phase 8：IM/Doc 全抽象 + Huly 接入 + 流程 MCP 化

> 版本：v0.1
> 日期：2026-05-17
> 作者：liuxin
> 状态：草案（待 gsd:plan-phase 走 research → plan → verify）
>
> **总目标**：让 offboarding-flow 的 IM 通道、协作文档通道、流程操作三类能力都**接口化 / 配置化**，使切换 Mattermost → Huly、Outline → Huly、增加 LLM 直接驱动流程都只需"加一个 Provider"或"加一个 MCP server"，不动业务代码。
>
> **关联设计文档**（已写）：
> - [`docs/plans/2026-05-17-huly-platform-integration-design.md`](docs/plans/2026-05-17-huly-platform-integration-design.md) — Huly 接入草图（含镜像清单 + sidecar 模式）
> - [`../agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md`](../agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md) — IM bot 通用配置抽象
> - [`README.md`](README.md) §3-§5 — 三系统身份同步 + magic-link token 设计

---

## 1. 背景与动机

### 1.1 当前痛点（v0.4 后的现状）

| 痛点 | 现状代码位置 | 影响 |
|---|---|---|
| IM listener 单一耦合 Mattermost | `workers/mattermost_listener.py` 行 41 `from mattermostautodriver import AsyncDriver` 直接 import | 想换 IM 平台必须重写 listener |
| dispatch 逻辑写在 listener 内 | `mattermost_listener.py:175-244` 拆 message → parse → intent → role → ctx 全混在 `_handle_event` 里 | 跨 IM 平台无法复用 |
| 协作文档调用混杂 | `outline/client.py` 是 Outline 专属客户端；`handover_service` / `meeting_service` 通过 Provider 走，但 listener / bot_service 里还有部分 outline 直调 | 抽象不彻底 |
| 流程操作只能通过 HTTP / IM | LLM 想推进流程要走 HTTP API，不便于 Claude / Cursor 等 MCP-aware 客户端集成 | 错失 MCP 生态 |
| Huly 在 v0.4 不支持 | 仅 Mattermost + Outline + Lark + WeCom/DingTalk stub | 客户已用 Huly 的场景无法对接 |

### 1.2 Phase 8 三件套

```
┌──────────────────────────────────────────────────────────────┐
│  Phase 8                                                     │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐ │
│  │ 8A. 抽象重构 │  │ 8B. Huly    │  │ 8C. 流程 MCP server  │ │
│  │  • IMListen │  │  • huly-    │  │  • node actions      │ │
│  │  • dispatch │  │    bridge   │  │    暴露为 MCP tools   │ │
│  │  • 提取       │  │    sidecar  │  │  • LLM 直接调用      │ │
│  │    dispatch │  │  • doc/im   │  │    advance/return/   │ │
│  │    _message │  │    provider │  │    reject 等          │ │
│  │  • Provider │  │  • service- │  │  • 不依赖 IM/Doc      │ │
│  │    Protocol │  │    token    │  │    通道               │ │
│  │    完善      │  │    认证      │  │                      │ │
│  └─────────────┘  └─────────────┘  └──────────────────────┘ │
│       ↓                ↓                     ↓               │
│       └────────────────┴─────────────────────┘               │
│                  零业务代码改动                                │
└──────────────────────────────────────────────────────────────┘
```

---

## 2. 范围

### 2.1 In Scope

| ID | 内容 |
|---|---|
| **8A 抽象重构** | |
| ABS-01 | 定义 `IMListener` Protocol（启停 / 事件订阅 / 反向 dispatch hook） |
| ABS-02 | 把 `mattermost_listener._handle_event` 行 175+ dispatch 逻辑提取为通用函数 `dispatch_message(sender, channel_id, channel_type, message, im_helpers)` |
| ABS-03 | `DocProvider` Protocol 加 `delete_collection / list_documents_in_collection / delete_document` 三个完整生命周期方法（Huly 需要） |
| ABS-04 | `IMProvider` Protocol 加 `register_command_listener(handler)` 反向订阅接口（统一 listener 模式） |
| ABS-05 | `bot_service.dispatch` 内部 if/elif 11 个分支重构为 HandlerRegistry 动态查表（参考 agent-builder im-bot 抽象草图） |
| ABS-06 | 把 `_NODE_META` 节点元数据（assignee / title / role）从代码搬到 `config/nodes.yaml` 或 DB 表，为生产模式查 `users.manager_email` 留 hook |
| **8B Huly Provider** | |
| HULY-01 | 拉所有 Huly 自托管镜像（9 个 hardcoreeng/* + 5 个基础设施），写 `scripts/pull_huly_images.sh` |
| HULY-02 | docker-compose.yml 加 `huly-stack` profile（CockroachDB + Redpanda + ES + MinIO + 9 个 Huly 服务）+ `huly` profile（仅 sidecar） |
| HULY-03 | 写 Node sidecar `backend/sidecars/huly-bridge/`（TypeScript + Express + `@hcengineering/api-client`） |
| HULY-04 | 用 **官方 service token 模式**（`generateToken(systemAccountUuid, ws, {service:'offboarding-bot'})`）注册 bot，不用 email/password |
| HULY-05 | 参考 fork [`hcengineering/platform/services/telegram-bot/pod-telegram-bot`](https://github.com/hcengineering/platform/tree/main/services/telegram-bot)，把命令处理改成转 HTTP 到 backend |
| HULY-06 | 实现 `huly_doc_provider.py` + `huly_im_provider.py`（HTTP 调 sidecar） |
| HULY-07 | 实现 `huly_listener.py` 或路由 `POST /api/internal/huly/event`（接收 sidecar 反向推送） |
| HULY-08 | 身份对齐：seed 时按业务 DB 13 个 users 批量在 Huly 建 account（`scripts/seed_huly_users.py`） |
| HULY-09 | E2E：用 browser-harness 截 Huly UI 上 it.charlie 起流程 + handover doc 真写入 Huly Wiki + 按员工分 Space |
| **8C 流程 MCP 化** | |
| MCP-01 | 用 [FastMCP](https://github.com/jlowin/fastmcp) 或 Python `mcp` SDK 写 `backend/mcp/offboarding_mcp_server.py` |
| MCP-02 | 暴露 MCP tools：`list_flows / get_flow / advance_node / return_node / reject_node / get_node_form / submit_handover_doc / get_user_assignments` |
| MCP-03 | 暴露 MCP resources：`flow://{flow_id}`（YAML 流程定义） / `node://{flow_id}/{node_id}`（节点状态 + 历史） |
| MCP-04 | MCP server 鉴权：accept Bearer token = 同 magic-link JWT（sub=username 决定调用者身份） |
| MCP-05 | MCP server stdio + HTTP（SSE）双模式，前者 Claude Desktop 用，后者 web LLM agent 用 |
| MCP-06 | E2E：Claude Desktop 配置 offboarding MCP → 用户对 Claude 说"帮我看看 it.charlie 的流程到哪一步了" → Claude 调 `get_flow` 返回 DAG 状态 |

### 2.2 Out of Scope（Phase 9+）

- ❌ Huly 内置 `tracker` / `project` 直接做离职流程编排（用户问"能否把离职流程封装成 MCP"——答：流程引擎仍在 LangGraph，Huly 仅作 IM/Doc 数据源 + MCP 提供给 LLM）
- ❌ Huly 替代业务 DB（Huly 跑 CockroachDB，我们跑 PostgreSQL，双库；不合并）
- ❌ MCP 暴露 AI 决策（advance / return / reject 仍必须人工最终确认，PRD §15.3 红线）
- ❌ 多 workspace / 多 tenant 隔离（v1 单 workspace）
- ❌ 流程模板可视化编辑器（agent-builder 项目的事，不在本项目）

---

## 3. 用户故事

### 3.1 运维侧

| 故事 | 描述 |
|---|---|
| US-OPS-1 | 作为运维，我希望切换 IM 平台只改 `.env` 一行 `IM_PROVIDER=huly`，不需要重启业务、不需要改 Python 代码 |
| US-OPS-2 | 作为运维，我希望在 `192.168.2.44` 跑一个脚本就拉齐所有 Huly 镜像，不需要手动 docker pull 14 次 |
| US-OPS-3 | 作为运维，我希望 Huly bot 凭证用 service token，不需要为 bot 单独维护一个真人账号密码 |

### 3.2 业务侧

| 故事 | 描述 |
|---|---|
| US-BIZ-1 | 作为 it.charlie，我希望既能在 Mattermost 也能在 Huly 对 bot 说"我要离职"启动流程，体验一致 |
| US-BIZ-2 | 作为 li.si（manager），我希望收到的审批邮件深链既能跳 nginx 反代下的前端（原模式），也能跳 Huly Wiki 文档关联节点的页面（如果客户用 Huly） |
| US-BIZ-3 | 作为 hr.alice，我希望在 Huly Wiki 看到每个员工独立的「离职 · {username}」Space，里面有 11 个节点的交接文档 |

### 3.3 AI 集成侧

| 故事 | 描述 |
|---|---|
| US-AI-1 | 作为 Claude Desktop 用户，我希望配置一个 MCP server 后能问 Claude"列出我负责的所有待审批离职流程"，Claude 调 MCP `get_user_assignments(username=me)` 直接返回 |
| US-AI-2 | 作为 Cursor 用户，我希望选中代码后问 "这次离职是哪个员工，看下他的设备归还节点的 result_text"，Cursor 通过 MCP `get_node_form` 拉数据 |
| US-AI-3 | 作为 admin，我希望禁用 MCP 写操作（advance/return/reject），只允许读，防 LLM 误推进流程 |

---

## 4. 功能需求清单（REQ）

### 4.1 抽象重构 (ABS) — 5 项

| REQ-ID | 描述 | 优先级 |
|---|---|---|
| REQ-ABS-01 | `IMListener` Protocol 定义 + 现有 MattermostListener 实现该 Protocol | P0 |
| REQ-ABS-02 | `dispatch_message` 函数提取 + MM listener 内部调用它 + 单元测试 | P0 |
| REQ-ABS-03 | `DocProvider` Protocol 补 3 个生命周期方法 + Outline/Lark/Mattermost provider 实现 | P0 |
| REQ-ABS-04 | `bot_service.dispatch` HandlerRegistry 重构（无业务行为变化，纯重构） | P1 |
| REQ-ABS-05 | `_NODE_META` 搬 YAML：`config/nodes.yaml` + loader + 单元测试 | P1 |

### 4.2 Huly 接入 (HULY) — 9 项

| REQ-ID | 描述 | 优先级 |
|---|---|---|
| REQ-HULY-01 | `scripts/pull_huly_images.sh` + `HULY_VERSION` env 变量 | P0 |
| REQ-HULY-02 | docker-compose `huly-stack` + `huly` profiles | P0 |
| REQ-HULY-03 | `backend/sidecars/huly-bridge/` Node 服务（service token 认证 + HTTP API + WS 订阅） | P0 |
| REQ-HULY-04 | `huly_doc_provider.py` 实现 Protocol 全部方法（含 8A 加的 3 个生命周期） | P0 |
| REQ-HULY-05 | `huly_im_provider.py` 实现 Protocol 全部方法 | P0 |
| REQ-HULY-06 | `huly_listener.py` 实现 `IMListener` Protocol（HTTP webhook 接收 sidecar 推送） | P0 |
| REQ-HULY-07 | `scripts/seed_huly_users.py` — 业务 DB 13 个 user 一次性同步 Huly | P0 |
| REQ-HULY-08 | E2E: it.charlie 在 Huly UI 起流程 → 完整跑完 → handover docs 在 Huly Wiki 可见（browser-harness 截图） | P0 |
| REQ-HULY-09 | `.env.example` 更新（HULY_* 占位变量） + README §1 加 Huly 部署段 | P1 |

### 4.3 流程 MCP 化 (MCP) — 6 项

| REQ-ID | 描述 | 优先级 |
|---|---|---|
| REQ-MCP-01 | `backend/mcp/offboarding_mcp_server.py` 用 FastMCP 框架 | P0 |
| REQ-MCP-02 | 7 个 read tools (`list_flows / get_flow / get_node_form / get_user_assignments / get_handover_docs / get_final_summary / get_meeting_summary`) | P0 |
| REQ-MCP-03 | 4 个 write tools (`advance_node / return_node / reject_node / submit_handover_doc`)，**默认禁用**，需 `MCP_ALLOW_WRITE=true` 才开 | P0 |
| REQ-MCP-04 | MCP 鉴权：Bearer token = magic-link JWT；sub 决定调用者身份，复用 `verify_actor_can_handle` 权限闸门 | P0 |
| REQ-MCP-05 | stdio mode（Claude Desktop） + HTTP/SSE mode（web agent） 双 transport | P1 |
| REQ-MCP-06 | E2E: Claude Desktop 配置 `claude_desktop_config.json` → 调 `get_flow` 返回 DAG（截图） | P1 |

---

## 5. 非功能需求

| ID | 描述 |
|---|---|
| NFR-01 | Provider 切换零业务代码改动：`.env` 改 `IM_PROVIDER` / `DOC_PROVIDER` 即可，pytest 全套 332 测试 0 回归 |
| NFR-02 | Huly sidecar 进程独立，挂掉不影响业务，`restart: unless-stopped` + healthcheck |
| NFR-03 | MCP server 默认只读，防 LLM 误推进流程 |
| NFR-04 | 所有 provider 凭证（Huly service token / MM bot token / Outline API token）通过 env 注入，gitleaks 拦截 |
| NFR-05 | Huly bridge 与 backend 之间用 `BRIDGE_TOKEN` 共享 secret 鉴权（HTTP X-Header） |
| NFR-06 | Huly sidecar 启动期不卡：连不上 Huly 时 retry 5 次后健康检查标 unhealthy，不阻塞 backend 启动 |
| NFR-07 | 现有 9 节点 + DAG + 邮件深链 + magic token 业务**零行为变化** — 仅多了 Huly 作为可选 provider |

---

## 6. 设计约束

| 约束 | 来源 | 含义 |
|---|---|---|
| C-1 | README §3 三系统身份同步 | username 仍是跨系统主键；Huly 用 `{username}@demo.local` 当 email |
| C-2 | README §5 magic-link 4 道保险 | MCP 鉴权复用同一套 JWT，不引入第二种 token 体系 |
| C-3 | CLAUDE.md §3.3 双层状态分离 | LangGraph checkpoint vs 业务 DB；MCP tools 只读业务 DB，不直接访问 checkpoint |
| C-4 | CLAUDE.md §3.4 节点幂等 | MCP write tools 必须 upsert 安全，与 HTTP API 同质 |
| C-5 | PRD §15.3 AI 边界 | MCP write tools 默认禁用；即使开启也走 `verify_actor_can_handle` 角色闸门 |
| C-6 | CLAUDE.md §1 并行优先 | Phase 8 三件套 8A/8B/8C 可并行开发（无写入冲突），用 gsd subagent-driven 调度 |

---

## 7. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| Huly TypeScript SDK 升级 break sidecar | 中 | 高 | 锁版本 + CI 跑契约测试 + 参考官方 telegram-bot 的兼容性策略 |
| MCP write tools 被 LLM 误用推进流程 | 中 | 高 | 默认禁用 + 必须 `MCP_ALLOW_WRITE=true` + tools 描述显式写"会影响业务"+ 复用 verify_actor_can_handle |
| Huly 服务集群占资源大（4-6GB RAM） | 高 | 中 | `--profile huly-stack` 可选；推荐生产独立部 Huly 集群 |
| sidecar 维护成本（多语言栈）| 中 | 中 | 仅 ~250 行 TS + Dockerfile，明确指责单一；不写复杂业务逻辑 |
| 测试覆盖率下降 | 中 | 中 | 8A 重构必须保持现有 332 测试通过 + 新增 ~50 单元/集成测试 |
| FastMCP 框架不稳定 | 低 | 低 | 退路：Python `mcp` 官方 SDK |

---

## 8. 验收标准（DoD — Definition of Done）

### 8.1 Phase 8 整体 DoD

- [ ] 现有 332 unit/integration tests + 27 skipped + 全部 E2E **0 回归**
- [ ] 新增 ~80 测试覆盖 Phase 8 三件套（unit + integration + 1 套 E2E with browser-harness）
- [ ] `.env` 改 `IM_PROVIDER=huly` + `DOC_PROVIDER=huly` 单测全过
- [ ] Phase 8 commit 全部通过 pre-commit hooks（gitleaks / ruff / mypy / 大文件 / format）
- [ ] E2E 报告 + 截图新增 `docs/e2e-test-report-phase-8-2026-XX-XX.md`

### 8.2 8A 抽象重构 DoD

- [ ] `IMListener` Protocol 在 `backend/src/offboarding_flow/im/protocol.py`
- [ ] `dispatch_message` 在 `backend/src/offboarding_flow/im/dispatcher.py`
- [ ] `MattermostListener` 实现 `IMListener` Protocol，集成测试调用真实 MM 容器
- [ ] `bot_service.dispatch` HandlerRegistry 重构后所有 11 个命令仍正常工作

### 8.3 8B Huly DoD

- [ ] `192.168.2.44` 拉齐 14 个 Huly 镜像
- [ ] `docker compose --profile huly-stack up -d` 在 60 秒内 ready（healthcheck 全绿）
- [ ] huly-bridge 用 service token 注册成功（log 显示 IntegrationKind='offboarding-bot' 已注册）
- [ ] it.charlie 在 Huly UI 对 bot 说"我要离职" → 真起流程
- [ ] 流程跑完后 Huly Wiki 出现 `离职 · it.charlie` Space + 11 个交接文档（含总报告）
- [ ] 切换回 `IM_PROVIDER=mattermost` 后所有 MM 功能依然正常

### 8.4 8C MCP DoD

- [ ] `backend/mcp/offboarding_mcp_server.py` 可用 `python -m offboarding_flow.mcp.server` 启动
- [ ] Claude Desktop 配置 `claude_desktop_config.json` 加入 offboarding MCP 后能识别 7+ tools
- [ ] `get_flow(flow_id=xxx)` 返回 markdown 格式 DAG 状态
- [ ] `get_user_assignments(username=hr.alice)` 返回 hr.alice 待处理节点清单
- [ ] write tools 默认 401 拒绝（`MCP_ALLOW_WRITE=false`）
- [ ] 启用 write + 用 hr.alice 的 magic JWT 调 `advance_node` 能真推进流程

---

## 9. 里程碑（粗排，待 GSD planner 细化）

| 子 phase | 内容 | 预估 |
|---|---|---|
| 8A.1 | IMListener Protocol + dispatch_message 提取 | 1 天 |
| 8A.2 | DocProvider 生命周期方法补全 + 现有 provider 实现 | 1 天 |
| 8A.3 | HandlerRegistry 重构 bot_service.dispatch | 1 天 |
| 8A.4 | `_NODE_META` → YAML 配置 | 0.5 天 |
| 8B.1 | 拉镜像 + docker-compose + huly-stack 跑通 | 1 天 |
| 8B.2 | sidecar TS 骨架 + service token 注册 | 1.5 天 |
| 8B.3 | sidecar HTTP API 实现（send_dm / post_channel / create_doc） | 2 天 |
| 8B.4 | sidecar WS 订阅 → POST backend | 1 天 |
| 8B.5 | huly_doc/im/listener provider 实现 | 1.5 天 |
| 8B.6 | seed_huly_users + 身份对齐 | 0.5 天 |
| 8B.7 | E2E browser-harness 全链路 | 1 天 |
| 8C.1 | FastMCP server 骨架 + 7 read tools | 1.5 天 |
| 8C.2 | 4 write tools + 鉴权 + 权限闸门 | 1 天 |
| 8C.3 | stdio + HTTP SSE 双 transport | 0.5 天 |
| 8C.4 | Claude Desktop E2E 截图 | 0.5 天 |
| 总计 | | **~16 工作日 / 3-4 周** |

---

## 10. 参考资料

- [Huly Platform](https://github.com/hcengineering/platform)
- [huly-selfhost](https://github.com/hcengineering/huly-selfhost)
- [Huly 官方 telegram-bot 参考实现](https://github.com/hcengineering/platform/tree/main/services/telegram-bot/pod-telegram-bot)
- [Huly AI Agent (Rust)](https://github.com/hcengineering/huly-ai-agent)
- [Model Context Protocol Spec](https://modelcontextprotocol.io/)
- [FastMCP](https://github.com/jlowin/fastmcp)
- [docs/plans/2026-05-17-huly-platform-integration-design.md](docs/plans/2026-05-17-huly-platform-integration-design.md) — Phase 8B 详细设计
- [../agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md](../agent-builder/docs/plans/2026-05-17-im-bot-abstraction-design.md) — Phase 8A 详细设计

---

## 11. 待 GSD planner 决策的开放问题

1. **8A/8B/8C 并行 vs 串行？** — 8A 提供的抽象层 8B/8C 都依赖；建议 8A 先行 1 周，8B/8C 并行 2 周
2. **MCP 鉴权是否复用 magic JWT 还是引入 API key？** — 倾向复用（NFR-04），但 LLM 不便处理短 TTL，要不要给 MCP token 更长 TTL（30 天）？
3. **Huly bot 命令需要重新写一套吗？** — `dispatch_message` 提取出来后 MM/Huly listener 共用同一套 handler，理论上 0 改动
4. **是否同时支持"流程定义 YAML 化"？** — 8A.4 把节点 meta 搬 YAML 是浅层；深层把 DAG 拓扑也搬 YAML 是 Phase 9 的事，不在本 PRD
5. **Huly 内置 tracker 是否要做"离职流程 = Huly Project"双向同步？** — 不做（Out of Scope §2.2 已明确），Huly 仅作 IM/Doc 数据源

---

*文档完*
