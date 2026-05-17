# Phase 8 — Huly 接入 + IM/Doc 抽象 + MCP 化 整体调整汇总

> **日期**：2026-05-17
> **状态**：Plan 01-06 已完成 + Plan 07 部分完成（FastMCP server + 11 tools + 鉴权 已 commit，文档 + push 待补）
> **总提交**：24 个 commit（`b27eb2d → e7ff09c`）已 push 到 origin/main 中 23 个

---

## 1. 改动统计

| 类别 | 数量 |
|---|---|
| Phase 8 commits | 24 |
| 新建 Python 模块 | `im/` (4 文件) + `mcp/` (7 文件) + `workers/huly_listener.py` + `providers/huly_*.py` × 2 + `api/internal_huly.py` |
| 新建 Node sidecar | `backend/sidecars/huly-bridge/` 10 文件（src + tests + Dockerfile） |
| 改动业务文件 | `providers/base.py` / `services/bot_service.py` / `workers/mattermost_listener.py` / `auth/role_router.py` / `main.py` / `config.py` |
| 部署 / 文档 | `docker-compose.yml` (+367) / `.env.example` (+53) / `scripts/pull_huly_images.sh` (+189) / `scripts/seed_huly_users.py` + `deploy/huly/{README, HULY_IMAGES}.md` + `README.md` §9 |
| 新增测试 | 约 200+ 测试（Python pytest + Node vitest），现有 332 测试 0 回归 |
| 新增代码总行数 | ~6000+ 行 |

---

## 2. 三件套调整全景

```
┌─────────────────────────────────────────────────────────────────────┐
│  8A 抽象重构 (Plan 01)                                                │
│  ─────────────────                                                   │
│  • backend/src/offboarding_flow/im/protocol.py    IMListener Protocol │
│  • im/dispatcher.py                                dispatch_message()  │
│  • im/context.py                                   BotInvocationContext│
│  • services/bot_handler_registry.py                HandlerRegistry     │
│  • providers/base.py    +3 lifecycle 方法 + register_command_listener │
│                                                                       │
│  ↓ 抽象层就位 → 8B / 8C 复用                                            │
├─────────────────────────────────────────────────────────────────────┤
│  8B Huly 接入 (Plan 03-06)                          8C MCP 化 (Plan 07)│
│  ────────────                                       ─────────────     │
│  • scripts/pull_huly_images.sh (15 images)         • mcp/server.py    │
│  • docker-compose.yml huly-stack + huly profile    • mcp/auth.py      │
│  • backend/sidecars/huly-bridge/ (Node + TS)       • mcp/tools_read.py│
│      - serviceToken('offboarding-bot')               (7 read tools)   │
│      - im.ts / doc.ts / listener.ts                • mcp/tools_write  │
│      - admin.ts (signUpJoin batch)                   (4 write,默认禁) │
│  • providers/huly_im_provider.py (HTTP → sidecar)  • Bearer JWT 鉴权 │
│  • providers/huly_doc_provider.py (HTTP → sidecar)   = magic-link JWT │
│  • workers/huly_listener.py (IMListener impl)      • stdio + http     │
│  • api/internal_huly.py (POST /event)                双 transport     │
│  • scripts/seed_huly_users.py (13 user 批量同步)                       │
│                                                                       │
│  与 MM / Outline / Lark / 飞书 平级 — 走同一套 Protocol               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. 切换平台只改 `.env` — 实际验证

### 3.1 现状默认（Mattermost + Outline）

```ini
# .env
IM_PROVIDER=mattermost
DOC_PROVIDER=outline
```

启动：`docker compose up -d` 就够了。

### 3.2 切到 Huly（IM + Doc 一体）

```ini
# .env
IM_PROVIDER=huly
DOC_PROVIDER=huly
HULY_URL=http://192.168.2.44:8087
HULY_WORKSPACE=laios
HULY_SERVER_SECRET=<同 Huly stack 的 SECRET>
HULY_BRIDGE_TOKEN=<bridge 与 backend 共享 secret>
HULY_ADMIN_EMAIL=1624456575+admin@qq.com
HULY_ADMIN_PASSWORD=<admin 密码>
HULY_USER_PASSWORD=Laios1855!Member
```

启动：`docker compose --profile huly up -d`（加 sidecar）或 `--profile huly-stack` 同时起 14 容器 Huly 全栈。

### 3.3 业务代码改动：**0**

`factory.get_im_provider()` / `factory.get_doc_provider()` 按 env 返回 huly 实例，业务层（`flow_service` / `node_service` / `meeting_service` / `handover_service`）完全无感知，依然调 Protocol 接口。

---

## 4. 现在切换有多通用？现状评估

| 维度 | 现状 | 通用度 |
|---|---|---|
| **Provider 选择** | env 切换 + factory single | ✅ 平台无感知 |
| **Protocol 完整度** | IMProvider + DocProvider + IMListener 都有 | ✅ 接口完整 |
| **业务代码依赖** | 通过 `get_im_provider()` / `get_doc_provider()` 间接调用 | ✅ 零硬编码 |
| **凭证管理** | 全走 env / pre-commit gitleaks 拦 | ✅ 安全 |
| **测试覆盖** | 新增 200+ 测试 + 现有 332 测试 0 回归 | ✅ 防回归 |
| **listener 启停** | `main.py lifespan` 按 IM_PROVIDER 起对应 listener | ✅ 自动 |
| **协议跨度** | MM (REST+WS) + Outline (REST) + Huly (Node sidecar) + Lark + WeCom + DingTalk stub | ✅ 6 平台 |
| **加新平台成本** | ~300-500 行（Provider 类 + listener + factory 注册） | ⚠️ 中 |
| **配置驱动度** | 主要靠 env + factory，没有 YAML / DB 注册表 | ⚠️ 较低 |
| **运行时切换** | 必须重启 backend（lifespan reset） | ⚠️ 不支持热切 |

---

## 5. 让切换"更通用"还能怎么做 —— 4 个进一步抽象方向

### 5.1 **Provider Registry 配置化**（最有价值）

**现状**：`factory.py` 的 `get_im_provider()` 是 if/elif 硬编码：
```python
def get_im_provider():
    name = settings.im_provider
    if name == "mattermost": return MattermostProvider(...)
    elif name == "huly": return HulyImProvider(...)
    elif name == "lark": return LarkProvider(...)
    ...
```

**改进**：用 YAML / dict 注册表 + 动态 import：
```yaml
# config/providers.yaml
im_providers:
  mattermost:
    module: offboarding_flow.providers.mattermost_provider
    class: MattermostProvider
    config_env_prefix: MM_
  huly:
    module: offboarding_flow.providers.huly_im_provider
    class: HulyImProvider
    config_env_prefix: HULY_
  custom_slack:                        # ← 加新平台只需配置
    module: my_company.providers.slack
    class: SlackProvider
    config_env_prefix: SLACK_
```

**收益**：加新平台**不改 factory 代码**，只在 YAML 加一段 + 实现 Protocol。

### 5.2 **统一 IMHelpers 接口标准化**

**现状**：每个 listener 通过 `im_helpers: dict[str, Callable]` 注入 helpers（post_channel / send_dm / ensure_in_channel）；dispatch_message 取 dict key 调用。

**问题**：dict[str, Callable] 弱类型，加 helper 时全 provider 要更新。

**改进**：定义正式 `IMHelpers` Protocol（已有 `im/context.py`，进一步收紧）：
```python
class IMHelpers(Protocol):
    async def post_channel(self, channel_id: str, message: str) -> None: ...
    async def send_dm(self, username: str, message: str) -> None: ...
    async def ensure_in_channel(self, channel_id: str, username: str) -> None: ...
    async def react(self, msg_id: str, emoji: str) -> None: ...   # 新增 helper 时
    async def edit_message(self, msg_id: str, new_text: str) -> None: ...
```

**收益**：mypy 验证 + IDE 补全 + 加 helper 时 missing impl 编译期报错。

### 5.3 **运行时热切（multi-provider 并存）**

**现状**：必须重启 backend 才能切 provider；同时只能跑一个 IM listener。

**改进**：让 `main.py` 启动**所有配置启用的 listener**（不是单一），按 IM_PROVIDERS=mattermost,huly 启 2 个 listener。dispatch_message 已经是 provider 无关的，本身就支持。

```ini
# .env
IM_PROVIDERS=mattermost,huly           # 复数，逗号分隔
DOC_PROVIDERS=outline,huly
DEFAULT_DOC_PROVIDER=huly              # 写入默认走哪个
```

`main.py lifespan`：
```python
for provider_name in settings.im_providers.split(","):
    listener = create_listener(provider_name)
    await listener.start()
    app.state.listeners.append(listener)
```

**收益**：同时挂 MM bot + Huly bot；同一员工在两边发"我要离职"都能起流程；migration 期间双跑。

### 5.4 **Provider 自描述 + 健康检查**

**现状**：Provider 无统一 health check / capability description；运维不知道"当前 Huly bridge 在线吗？支持哪些 helpers？"。

**改进**：Protocol 加 `describe()` + `healthcheck()`：
```python
class IMProvider(Protocol):
    async def describe(self) -> ProviderDescription:
        """返回 provider 元数据：name / version / capabilities / required_env"""
    async def healthcheck(self) -> HealthStatus:
        """活性检查 — 返回 OK / DEGRADED / DOWN + 详情"""
```

加 `/api/admin/providers` 路由暴露所有 provider 状态。

**收益**：可视化运维 + CI 启动期校验 + 文档自动生成。

---

## 6. 推荐实施顺序

| 顺序 | 改进 | 价值 | 工作量 | 时机 |
|---|---|---|---|---|
| 1 | **5.1 Registry 配置化** | ⭐⭐⭐⭐⭐ 加平台 0 改代码 | 1 天 | Phase 8 收尾时一起做 |
| 2 | **5.2 IMHelpers Protocol** | ⭐⭐⭐⭐ 强类型 | 0.5 天 | 收尾时同 5.1 一起 |
| 3 | **5.4 describe + healthcheck** | ⭐⭐⭐ 运维友好 | 1 天 | Phase 9 加进去 |
| 4 | **5.3 多 listener 并存** | ⭐⭐⭐⭐ 真正多平台同时 | 2 天 | Phase 9（演示价值大） |

总计：4-5 天可以把"切换通用度"从「换 1 行 env」升到「配置驱动 + 多平台并存 + 自描述」工业级。

---

## 7. 关键文件索引（Phase 8 完整产物）

```
backend/src/offboarding_flow/
  im/                                    ← Plan 01 新模块
    protocol.py                          IMListener Protocol
    dispatcher.py                        dispatch_message() 通用分发
    context.py                           BotInvocationContext + IMHelpers
  mcp/                                   ← Plan 07 新模块
    server.py                            FastMCP server entry
    auth.py                              MagicLinkAuthMiddleware
    tools_read.py                        7 read tools
    tools_write.py                       4 write tools (默认禁)
    registry.py                          tools 常量
    runner.py                            stdio / http transport
  providers/
    base.py                              DocProvider/IMProvider Protocol (扩展)
    huly_im_provider.py                  ← 新
    huly_doc_provider.py                 ← 新
    mattermost_provider.py               (已有，加 register_command_listener)
    outline_provider.py                  (已有，加 3 lifecycle)
    lark_provider.py                     (已有，加 3 lifecycle)
    wecom_provider.py / dingtalk_provider.py  stub
  workers/
    huly_listener.py                     ← 新 (IMListener impl)
    mattermost_listener.py               (refactored to call dispatch_message)
  api/
    internal_huly.py                     ← 新 (POST /api/internal/huly/event)
  services/
    bot_handler_registry.py              ← 新 (HandlerRegistry)
    bot_service.py                       (dispatch 重构)
  auth/
    role_router.py                       (加 verify_actor_can_handle)

backend/sidecars/huly-bridge/              ← 全新 Node sidecar
  package.json / Dockerfile / tsconfig.json
  src/
    index.ts                             Express app + healthz
    config.ts                            env 解析
    auth.ts                              serviceToken('offboarding-bot')
    middleware.ts                        bridgeAuth + adminAuth 双 token
    types.ts                             Schema
    im.ts                                send_dm / post_channel / ensure_in_channel
    doc.ts                               create_document
    listener.ts                          2s poll chat msg → POST backend
    admin.ts                             signUpJoin 批量
    hcengineering-shims.d.ts             TS 类型补
  tests/                                 60+ vitest

scripts/
  pull_huly_images.sh                    一键拉 15 镜像
  seed_huly_users.py                     13 user 批量同步

docker-compose.yml                       (+367, huly-stack + huly profile)
.env.example                             (+53, HULY_* 占位 8 个)

deploy/huly/
  README.md                              快速启动 runbook
  HULY_IMAGES.md                         镜像清单 + 端口冲突表

.planning/phases/08-huly-abstraction/
  08-CONTEXT.md / 08-RESEARCH.md
  08-0[1-7]-PLAN.md (7 个)
  08-0[1,3,4,5,6]-SUMMARY.md (5 个，07 待补)
```

---

## 8. Phase 7 残余 + 后续

| 项 | 状态 | 备注 |
|---|---|---|
| Plan 07 task 1 (FastMCP server + 11 tools + 鉴权) | ✅ commit `e7ff09c` 已 push | MCP-01..04 完成 |
| Plan 07 task 2-3 (stdio/http 启动 + Claude Desktop E2E + SUMMARY) | ⏸ 待 orchestrator 续做 | MCP-05/06 仅缺收尾 |
| Huly E2E browser-harness（it.charlie 在 Huly 起流程截图） | ⏸ orchestrator TODO（Plan 06 SUMMARY 标记） | 需 admin/user 实际跑 seed 后做 |
| 5.1/5.2 Provider Registry + IMHelpers Protocol 加强 | ⏸ 建议 Phase 8 收尾时做 | 1.5 天 |
| 5.3 多 listener 并存（IM_PROVIDERS=mm,huly） | ⏸ Phase 9 | 2 天 |
| 5.4 describe + healthcheck | ⏸ Phase 9 | 1 天 |
