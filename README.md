# offboarding-flow — AI 驱动的离职流程执行系统

> 演示项目：一名 IT 工程师从 Mattermost 对 @bot 说「我要离职」开始，到 HR 终审 + 申请人最终确认 + 自动归档完成，全链路由 LangGraph 状态机驱动。配套：QQ 邮件深链一键登录、Outline 协作文档自动归档（按员工分文件夹）、AI 节点交接报告 + 总报告、会议总结子系统、自然语言意图路由。
>
> 目标：内网局域网部署，单机 Docker Compose 跑通**真实**邮件 / IM / 协作文档 / LLM 全链路（不是 mock）。

---

## 1. 测试环境

| 类别 | 实际部署 |
|---|---|
| 宿主机 | `192.168.2.44`（Windows 11 Pro，GigaByte 内网） |
| 编排 | Docker Desktop + Docker Compose v5.1.3 |
| 数据库 | PostgreSQL 16（容器 `offboarding-postgres`，独立 5433 端口） |
| 缓存 | Redis 7（容器 `offboarding-redis`，独立 6380 端口） |
| 后端 | FastAPI + LangGraph 1.x + SQLAlchemy async + PostgresSaver |
| 前端 | Next.js 15 (App Router) + Tailwind v4 + shadcn/ui — `output: 'export'` 静态导出 |
| 反代 | nginx（容器内，含 SPA 动态路由 fallback） |
| 邮件 | QQ SMTP（真账号，演示模式收件人统一映射到 `1624456575@qq.com` / `1691517500@qq.com` / `jingzhi.lu@wayz.ai`） |
| IM | Mattermost Team Edition（`:8065`，team `laios`） |
| 协作文档 | Outline（`:3001`，bot token 接入） |
| 对象存储 | MinIO（`:9001` console / `:9000` API） |
| LLM | GLM-4-flash（OpenAI 兼容 `chat.completions`，演示场景免费够用） |
| `APP_MODE` | `demo`（生产模式只切环境变量，邮件走真实收件人） |

启动命令（在 `192.168.2.44` 上）：

```bash
docker compose --env-file .env up -d
```

E2E 测试用 [`browser-use/browser-harness`](https://github.com/browser-use/browser-harness) 连本机 Chrome CDP，
集成测试用 `pytest-asyncio` + `httpx.AsyncClient` + `asgi-lifespan`（**不 mock DB / 不 mock SMTP**）。

---

## 2. LangGraph 状态机做了什么

整个离职流程是一张有 **11 个业务节点 + 1 个自动归档节点** 的 DAG：

```
apply (AutoNode)
   └─ manager_review (人工)
        ├─ return ──→ 回到 apply（路由后申请人收新邮件补材料）
        ├─ reject  ──→ 终止
        └─ advance ──→ hr_initial (人工)
                          ├─ return ──→ 回到 apply
                          ├─ reject  ──→ 终止
                          └─ advance ──→ ┬──→ device_return
                                          ├──→ access_revoke
                                          ├──→ knowledge_handover    (5 并行)
                                          ├──→ finance_settle
                                          └──→ legal_sign
                                                 │ (fan-in)
                                                 ▼
                                           hr_final (人工)
                                            ├─ return ──→ 回 hr_initial
                                            ├─ reject  ──→ 终止
                                            └─ advance ──→ applicant_final_confirm (人工)
                                                              ├─ return ──→ 回 hr_final
                                                              └─ advance ──→ auto_archive_to_storage (AutoNode)
                                                                                    │
                                                                                    ▼
                                                                             flow.status = completed
```

### 2.1 节点推进机制

- **人工节点**：函数体内 `interrupt(payload)`，LangGraph 收到 `Command(resume=...)` 才继续
- **AutoNode**：直接 return，graph 自动 advance 到下一节点
- **条件路由**：`graph.add_conditional_edges` 根据当前节点 `current_action`（advance / return / reject）跳目标节点
- **并行 + fan-in**：5 个人工节点 fan-out 后 fan-in 到 `hr_final` 单点

### 2.2 双层状态分离（项目最深的设计约束）

| 层 | 谁管 | 用途 |
|---|---|---|
| **LangGraph checkpoint** (schema `langgraph`，pickle) | `PostgresSaver` 自管 | 引擎私有，恢复 / interrupt resume 必需 |
| **业务表** (schema `app`：`flow_instances` / `node_states` / `action_logs` / `notifications` / `notification_outbox` / `users`) | 业务代码 | UI / 审计 / 报表的 source of truth |

节点函数模板：

```python
async def manager_review(state: OffboardingState) -> dict:
    if is_first_entry(state):
        # 业务层：upsert node_states + 入队邮件 + 写 action_logs
        await on_first_entry(...)
    payload = interrupt({...})       # ← 这里抛 GraphInterrupt，函数会重跑
    # resume 后：双写 — 业务表 update + 返回 dict 让 LangGraph 推进
    await on_resume(payload)
    return {"current_action": payload["action"]}
```

**幂等性**：`interrupt()` 抛 `GraphInterrupt` 后节点函数会重跑，所有 INSERT 必须 upsert
（`ON CONFLICT DO NOTHING/UPDATE`），`notification_outbox` 加 `UNIQUE(flow_id, node_state_id, channel)`
防重复发邮件。

### 2.3 fan-in 冲突修复

5 并行节点同时 update `current_action / context` 时 LangGraph 默认会抛
`InvalidUpdateError: Can receive only one value per step`。解法在
`backend/src/offboarding_flow/flow_engine/state.py`：

- `current_action` 加 `_take_latest` reducer（取并行分支里最后写入的那一个）
- `context` 加 `_merge_context` reducer（dict 合并而非覆盖）

---

## 3. 设计难点 ① — 三套系统的身份同步是怎么维护的

系统横跨 3 个独立账号体系：

| 系统 | 用户域 | 主键 |
|---|---|---|
| 业务 DB | PostgreSQL `app.users` | `username` (unique) |
| Mattermost | 自带 user 系统 | `username` (unique，team-scoped) |
| Outline | 自带 user 系统 | `email` (unique，team-scoped) |

### 3.1 不是「写死」也不是「共享数据库」，而是「以 username 为跨系统主键 + 各自 ensure_user」

```
                  业务 DB (source of truth)
                  ┌───────────────────────┐
                  │ users(username, email, │
                  │  role, manager_email)  │
                  └────────┬───────────────┘
                           │
        ┌──────────────────┼─────────────────────┐
        │                  │                     │
        ▼                  ▼                     ▼
  Mattermost          Outline             邮件 (QQ SMTP)
  username = it.charlie  email + name      To: email
  ↑ seed-mattermost.sh   ↑ ensure_users()  ↑ resolve_demo_inbox(username)
  一次性脚本             懒加载，每次发  按 username 映射真实收件人
                         doc 时检查 +
                         缺失时 create
```

具体落地：

1. **业务 DB 是 source of truth**（`backend/src/offboarding_flow/state_store/models.py` `class User`）
   - `username` 为唯一主键（例：`it.charlie`、`hr.alice`、`li.si`）
   - 13 个演示账号由 `scripts/seed_demo_data.py` 一次性写入
2. **Mattermost** 用 `deploy/mattermost/seed-mattermost.sh` 调 `mmctl user create` 批量创建同 username 账号
   - 密码统一 `laios1855`（演示用，已 `.gitignore` 真实凭证）
   - 见 `deploy/mattermost/ACCOUNTS.md`
3. **Outline** 不预 seed — 第一次给某个 username 发 handover doc 时，`outline_provider.ensure_users()` 调
   Outline API `users.invite` 自动 invite 同 email 的账号（懒加载）
4. **跨系统对齐键**：所有代码统一用 **`username`** 作为外键
   - LangGraph 节点 `assignee` 字段存 `username`
   - 邮件 `To` 用 `users.email` lookup
   - Mattermost DM 用 `bot.users.get_user_by_username(username)` 拿 mm user id
   - Outline doc 的 `collaboratorIds` 由 `ensure_users` 返回的 outline user id 提供

### 3.2 Bot 收消息时怎么对齐回本地 username

`mattermost_listener` 收到 `posted` 事件时拿到 `post.user_id`（MM 内部 id），需要倒查本地 username：

```python
# workers/mattermost_listener.py
user_info = await driver.users.get_user(post.user_id)
mm_username = user_info["username"]   # ← MM 那边的 username
# 与本地 users.username 完全一致（seed 时就锁死同名）
stmt = select(User).where(User.username == mm_username)
local_user = (await session.execute(stmt)).scalar_one_or_none()
```

如果对齐失败（外部新建账号但没 seed 进业务 DB），bot 友好拒绝并提示 `users-sync` 命令。

### 3.3 用户运行时同步命令 `users-sync`

`bot_service.handle_users_sync` 触发 `outline_provider.ensure_users(all_users)`，把当前业务 DB 里所有 users
批量 invite 到 Outline / Mattermost（Mattermost 已 seed 过通常 no-op）。这是兜底机制，让运维不用 SSH 上去手跑 seed 脚本。

---

## 4. 设计难点 ② — 三套系统的状态同步是怎么维护的

> 三套系统：**LangGraph 引擎 / 业务 DB / 前端 UI**（Mattermost / Outline 是输出端，不持有状态）。

### 4.1 引擎 ↔ 业务 DB（双层状态分离，§2.2 已讲）

- 节点函数体内**先**业务表事务 commit，**才**返回让 LangGraph 推进
- 反过来 LangGraph 收 `Command(resume)` 触发节点重跑时，业务表 upsert 保护重复操作不报错
- 前端**绝不**直接读 LangGraph checkpoint，只读业务表

### 4.2 业务 DB ↔ 前端（拉取 + 不订阅）

v1 简化：前端按需 GET `/api/flows/{id}/nodes`，不上 WebSocket / SSE
（DAG 状态 / 进度 / handover_docs 一次拉齐），节点 advance 后页面 router push 强制 reload。

`my/flows/page.tsx` 把 `done = nodes.filter(n => n.status === 'done' || n.status === 'returned').length`，
分母固定 11，避免演示退回路径下 manager_review 一直留在 returned 导致 10/11 永远卡 91%。

### 4.3 业务 DB ↔ Mattermost / Outline（事务外 fire-and-forget）

handover doc / 会议 doc 生成走 `asyncio.create_task` fire-and-forget，**不参与业务事务**：

- 业务表事务 commit 后才异步发起 LLM + Outline / IM 调用
- 单点失败时：DB 状态正确推进，仅外部副作用缺失（log warning），不会回滚业务
- 「总报告」节点 (`_trigger_final_summary_async`) 用 poll 等所有 handover docs 写齐才聚合
  （最多 30 轮 × 3s = 90s），保证链接完整

---

## 5. 设计难点 ③ — magic-link token 生成 + 身份一致性怎么保证

邮件 / Mattermost 通知里都内嵌「立即处理」深链：

```
http://192.168.2.44/flow/handle?token=<jwt>&flow_id=<uuid>&node_id=<uuid>
```

### 5.1 Token 结构（HS256 JWT，`backend/src/offboarding_flow/auth/`）

```python
class JWTPayload(BaseModel):
    sub: str            # 操作人 username，跨系统对齐主键
    email: str          # 冗余字段，免 token 解码后再查 DB
    role: str           # applicant / manager / hr / it / finance / legal / kb_owner
    flow_id: str        # UUID
    node_id: str        # 当前节点 UUID（决定登录后落地页）
    iat: int            # 签发时间
    exp: int            # 过期时间（默认 7 天）
    jti: str            # 一次性消费 token id（防被截获重放）
```

### 5.2 签发链路

```
notification_service.enqueue_node_email(node)
   ↓
auth.deep_link.build_deep_link(token, payload, base_url)
   ├── jwt_service.encode(payload)         # HS256 + JWT_SECRET (env)
   └── 拼 URL query string
   ↓
邮件模板 {{deep_link_url}}
   ↓
outbox_drain 异步出栈 → email_sender 真发 QQ SMTP
```

### 5.3 消费链路（一键登录）

```
浏览器点深链 → /flow/handle?token=...
   ↓
backend POST /api/auth/handle
   ├── jwt_service.decode(token)         # 验签 + exp + Pydantic 校验
   ├── jti_service.consume(jti)           # Redis SETNX 一次性消费（防重放）
   ├── session_service.issue_session(...) # encode_session() 签发 cookie JWT
   └── 返回 {role, redirect_to, sub, ...}
   ↓
frontend handle/page.tsx
   ├── 非申请人 + URL 含 flow+node → /flow/{flow_id}/node/{node_id}/
   └── 申请人 → /my/flows/
```

### 5.4 身份一致性的 4 道保险

| # | 保险 | 实现 |
|---|---|---|
| 1 | **签名验证** | HS256 + `JWT_SECRET`（仅 env 注入，不进 git，`.env.example` 占位 `changeme_in_real_env`） |
| 2 | **重放防御** | `jti` 一次性消费 — Redis `SETNX offboarding:jti:{jti} 1 EX <ttl>`，第二次同 token 点击直接拒 |
| 3 | **TTL 强制过期** | `exp` 默认 7 天，`leeway=0` 严格判定（不允许 clock skew） |
| 4 | **subject = username** | `sub` 字段与业务 DB `users.username` 完全一致；任何 backend handler 拿到 session 都用 `sub` 直查 users 表，不存第二份镜像 |

### 5.5 角色与权限

JWT `role` 字段决定登录后能看到的视图：

- `applicant` → `/my/flows/`（DAG + handover docs + 进度）
- `manager` / `hr` / `it` / `finance` / `legal` / `kb_owner` → `/flow/{id}/node/{id}/`（三态决策表单）
- 任何角色 + URL 显式带 flow+node：覆盖默认 redirect，直接去节点处理页（处理跨流程 review）

后端 handler 在每个节点 advance 前再次 `verify_actor_can_handle(node, session.sub, session.role)`
做权限闸门 — token role 不能被前端篡改绕过（cookie 也是 JWT 签名的）。

---

## 6. 关键文件索引

```
backend/src/offboarding_flow/
  flow_engine/
    graph.py                  ─ LangGraph DAG 定义 + 条件路由
    state.py                  ─ OffboardingState + reducer (fan-in fix)
    nodes/                    ─ 11 个节点函数（含 AutoNode）
  auth/
    jwt_service.py            ─ encode / decode JWT (HS256)
    jti_service.py            ─ Redis 一次性 jti 消费
    deep_link.py              ─ build_deep_link
    session_service.py        ─ issue_session / cookie
  services/
    flow_service.py           ─ create_flow + bind 初始节点
    node_service.py           ─ advance/return/reject + 双写
    handover_service.py       ─ AI 节点交接 + 总报告
    meeting_service.py        ─ 会议三层 AI 分析 + _normalize_owners
    bot_intent_router.py      ─ LLM 自然语言意图分类
    notification_service.py   ─ outbox 入队 + 邮件模板
  workers/
    mattermost_listener.py    ─ WebSocket bot 长连
    outbox_drain.py           ─ outbox → email_sender / im_provider
  providers/
    base.py                   ─ DocProvider / IMProvider Protocol
    outline_provider.py       ─ Outline 真接入
    mattermost_provider.py    ─ MM 真接入
    lark_provider.py          ─ 飞书真接入
  state_store/
    models.py                 ─ User / FlowInstance / NodeState / ActionLog / Notification
    repositories.py           ─ 含 upsert 幂等接口
  llm/
    glm.py                    ─ GLM-4-flash 客户端
    prompts.py                ─ 8 个 prompt 模板

frontend/
  app/
    my/flows/page.tsx         ─ 申请人首页 + DAG + 进度
    flow/handle/page.tsx      ─ magic link 消费 + 跳转
    flow/[flow_id]/...        ─ 节点处理 / 申请人最终确认
  components/flow/
    flow-diagram.tsx          ─ React Flow + dagre DAG
    node-form.tsx             ─ 三态决策表单
  lib/api.ts                  ─ FlowDetail / NodeDetail 类型

deploy/
  mattermost/
    seed-mattermost.sh        ─ 13 个 MM 账号一次性创建
    ACCOUNTS.md               ─ 演示账号清单
  nginx/nginx.conf            ─ SPA 动态路由 fallback
  init-db.sql                 ─ DB schema 初始化

scripts/
  seed_demo_data.py           ─ 业务 DB 13 个 users + 可选起首个 flow
  deploy_to_192_168_2_44.sh   ─ 一键打包 + scp + docker compose up
  dev_reset.sh                ─ 本地清流 + 重 seed

docs/
  e2e-test-report-2026-05-17.md           ─ 完整 E2E 测试报告（it.charlie 主线）
  offboarding-e2e-test-2026-05-17-final.md ─ 离职流程分步截图详解
  meeting-summary-e2e-test-2026-05-17.md  ─ 会议总结子系统报告（含 NL 路由）
  DEMO_RUNBOOK.md                          ─ 演示脚本
  e2e-screenshots-2026-05-17-final/        ─ 22 张截图覆盖完整链路
```

---

## 7. 测试 & 报告

| 文档 | 内容 |
|---|---|
| [`docs/e2e-test-report-2026-05-17.md`](docs/e2e-test-report-2026-05-17.md) | it.charlie 离职完整 E2E（含 @bot 起流程 + 退回 + AI 报告 + 会议总结 + NL 路由） |
| [`docs/offboarding-e2e-test-2026-05-17-final.md`](docs/offboarding-e2e-test-2026-05-17-final.md) | 离职流程逐节点截图详解 |
| [`docs/meeting-summary-e2e-test-2026-05-17.md`](docs/meeting-summary-e2e-test-2026-05-17.md) | 会议总结子系统 + @unknown 兜底 + 自然语言路由 |
| [`CHANGELOG.md`](CHANGELOG.md) | 按 Phase 拆分的所有迭代记录 |

测试命令（在 `backend/` 目录）：

```bash
uv run pytest                                  # 单测 + 集成（332 PASS / 27 skipped）
uv run pytest tests/e2e -k full_flow           # 全流程 E2E（pytest-asyncio + real DB）
```

E2E 浏览器自动化用 `browser-use/browser-harness` 直连本机 Chrome CDP（不另启 headless）。

---

## 8. 凭证安全

- `.env` 已 `.gitignore`，仅 `.env.example` 进 git（占位 `changeme_in_real_env`）
- 凭证清单：`POSTGRES_PASSWORD` / `JWT_SECRET` (64 字符) / `SMTP_PASSWORD`（QQ 授权码 16 位）/
  `GLM_API_KEY` / `MATTERMOST_BOT_TOKEN` / `OUTLINE_API_TOKEN` /
  `HULY_SERVER_SECRET` / `HULY_BRIDGE_TOKEN` / `HULY_ADMIN_TOKEN`（Phase 8B）
- pre-commit `gitleaks` 钩子拦截硬编码 secret（已验证：当前所有 provider 通过 settings/env 读，无硬编码）

---

## 9. Huly 集成部署（Phase 8B，可选）

> 离职流程支持把 IM/Doc 通道切换到 Huly Platform。默认 `IM_PROVIDER=mattermost DOC_PROVIDER=outline`
> 时本节可跳过。

### 9.1 前置条件

- `192.168.2.44` 已部署 Huly v0.7.423 14 容器（参考 `deploy/huly/HULY_IMAGES.md`）
- Huly workspace `laios` 已通过 Huly UI 手动创建
- 已有 Huly admin 账号（email/password）— 通常是首次安装时创建的 super admin

### 9.2 步骤 1 — 配置 .env

复制 `.env.example` 中的 HULY_* 段到 `.env`，填入真值：

| 变量 | 用途 | 来源 |
|---|---|---|
| `HULY_VERSION=v0.7.423` | 业务版本（11 镜像共用） | 固定 |
| `HULY_URL=http://192.168.2.44:8087` | Huly Front 入口 | 部署 IP |
| `HULY_ACCOUNTS_URL=http://192.168.2.44:3007` | Accounts API | 部署 IP |
| `HULY_WORKSPACE=laios` | 目标 workspace | UI 手建 |
| `HULY_SERVER_SECRET=<openssl rand -hex 32>` | HMAC 密钥 | 必须与 huly-stack 同值 |
| `HULY_BRIDGE_TOKEN=<openssl rand -hex 16>` | sidecar 通信 token | 新生成 |
| `HULY_BRIDGE_URL=http://huly-bridge:7777` | sidecar URL | 默认 |
| `HULY_ADMIN_EMAIL=admin@huly.local` | Huly admin 邮箱 | UI 创 |
| `HULY_ADMIN_PASSWORD=<from UI>` | Huly admin 密码 | UI 创 |
| `HULY_ADMIN_TOKEN=<openssl rand -hex 32>` | sidecar admin 二级 token | 新生成 |
| `HULY_USER_PASSWORD=<演示统一密码>` | 13 seed 用户默认密码 | 自定义 |
| `HULY_BOT_ACCOUNT_UUID=` | bot 真账号 UUID | seed 后填 |
| `HULY_MINIO_USER/PASSWORD` | huly-stack MinIO 凭证 | UI 创 |

### 9.3 步骤 2 — 启动 huly-bridge sidecar

```bash
docker compose --profile huly up -d huly-bridge
# 等 30 秒 healthcheck 转绿
curl http://localhost:7777/healthz  # 应返回 {ok: true, huly_connected: true}
```

### 9.4 步骤 3 — Seed 13 个用户到 Huly

```bash
# 先 dry-run 预览
docker exec offboarding-backend uv run python /app/scripts/seed_huly_users.py --dry-run

# 真 seed
docker exec offboarding-backend uv run python /app/scripts/seed_huly_users.py

# 期望输出末行：[seed_huly_users] === DONE: seeded=13, skipped=0, failed=0 (total=13) ===
# 重跑同环境第二次：seeded=0, skipped=13, failed=0（幂等验证）
```

### 9.5 步骤 4 — 切换业务 backend 到 Huly

修改 `.env`：

```
IM_PROVIDER=huly
DOC_PROVIDER=huly
```

重启 backend：

```bash
docker compose restart backend
# 日志应显示：[huly_listener] 启动（webhook 模式）
```

### 9.6 步骤 5 — 验证

打开 Huly UI（http://192.168.2.44:8087），用 `it.charlie` 登录（密码 = `HULY_USER_PASSWORD`）
→ 在与 `offboarding-bot` 的 DM 中输入「我要离职」
→ bot 应回复「您的离职流程已启动…」
→ 业务 DB `app.flow_instances` 表应有新行（`employee_id='it.charlie'`）

### 9.7 回滚

```
IM_PROVIDER=mattermost
DOC_PROVIDER=outline
```

重启 backend 即可。**13 个 Huly account 不会自动删除**（需手动在 Huly admin UI 删除）。

### 9.8 安全建议

- seed 完后清空 `HULY_ADMIN_*` 凭证 + `HULY_ADMIN_TOKEN`，让 sidecar admin 路由不挂载，纯业务安全
- `HULY_USER_PASSWORD` 仅演示用；生产场景应为每个用户生成独立密码（修改 `scripts/seed_huly_users.py`）
- `HULY_BRIDGE_TOKEN` + `HULY_ADMIN_TOKEN` 是双重保护，缺一道都不能调 admin 路由

---

## 10. License & Attribution

演示项目，作者 `LaiosOvO`。代码由 Claude Code (Anthropic) 协助生成。
