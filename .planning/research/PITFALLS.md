# Pitfalls Research — LangGraph + FastAPI + Next.js 离职流程系统

**Domain:** State-machine workflow engine（人工介入流程 / 双层状态 / 双通道通知 / 演示导向）
**Researched:** 2026-05-16
**Confidence:** HIGH（多数验证自官方文档 + GitHub issues；演示场景类 pitfall 基于本项目 PRD §7.4 / §9.1 / §10 推导，标 MEDIUM）

> **使用说明**
> - 每条 pitfall 标注 **严重度**（致命 / 改进 / 次要）和 **演示标签**（[DEMO-ONLY] = 仅在演示场景出现 / [PROD-ONLY] = 仅在生产场景关键 / 不标即两者都适用）
> - 每条都给出 *Warning signs*（什么 log / 测试失败 = 这个坑）和 *Prevention*（具体代码 / 配置）
> - **Phase 映射**对应推荐的 6 phase 拆分：P1 Backend骨架 + LangGraph + Docker / P2 业务表 + 节点函数双写 / P3 鉴权 + 深链 / P4 通知（邮件 + Mattermost）+ Seed / P5 前端 + 演示模式 / P6 部署 + 端到端联调

---

## Critical Pitfalls（致命：会让 demo 跑不通 / 数据不一致 / 安全事故）

### Pitfall 1: PostgresSaver 没调 `.setup()` 或连接配错 [致命]

**What goes wrong:**
首次启动 LangGraph 时报 `relation "checkpoints" does not exist`，或 checkpoint 写入后 commit 不持久（重启即丢）。

**Why it happens:**
`PostgresSaver` / `AsyncPostgresSaver` 需要显式调 `.setup()` 创建 4 张表（`checkpoints` / `checkpoint_writes` / `checkpoint_blobs` / `checkpoint_migrations`）；当**手动创建** `psycopg` 连接传给 saver 时，必须设置 `autocommit=True` + `row_factory=dict_row`，否则 setup 的 DDL 不会提交。

**How to avoid:**
```python
# backend/app/flow/checkpointer.py
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

async def build_checkpointer(dsn: str) -> AsyncPostgresSaver:
    pool = AsyncConnectionPool(
        conninfo=dsn,
        max_size=20,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        open=False,
    )
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    await saver.setup()   # 幂等，每次启动都跑一次没关系
    return saver
```
- 用上下文管理器：`async with AsyncPostgresSaver.from_conn_string(dsn) as saver: await saver.setup()`
- 把 checkpoint 放到独立 schema：`CREATE SCHEMA langgraph; SET search_path=langgraph,public;`，业务表放 `public`，避免 schema 冲突
- 启动健康检查：`SELECT count(*) FROM langgraph.checkpoints` 返回 0+ = 表已建

**Warning signs:**
- `psycopg.errors.UndefinedTable: relation "checkpoints" does not exist`
- `prepare_threshold` 报错（PgBouncer transaction pooling 不兼容 prepared statements → 必须设 0）
- 重启后 `thread_id` 找不到旧 state

**Phase to address:** P1（Backend 骨架 + LangGraph 启动）

---

### Pitfall 2: 节点函数双写不在同一事务中（业务表与 LangGraph 不一致）[致命]

**What goes wrong:**
节点函数先 `await state_store.complete_node_state(...)` 写业务表成功，再 `graph.update_state(...) + graph.ainvoke(None, ...)` 失败 → 业务表显示 "done" 但流程 "卡死" 在 interrupt 状态，再也推不动。

**Why it happens:**
PRD §5.3.2 说"任何一边失败要回滚另一边"，但 LangGraph 的 `ainvoke` 是异步且**不可回滚**（checkpoint 已经写入）。开发者天真地用 `try/except` 包裹是不够的，因为 ainvoke 内部又有多次 DB 写入。

**How to avoid:**
**先 LangGraph 后业务表 + Outbox 模式**：

```python
# backend/app/api/flow_actions.py
async def submit_action(flow_id, node_id, action, result_text, reason, actor):
    async with db.transaction() as tx:
        # 1. 业务表写 action_logs（pending 状态）+ 标记 node_state 为 "submitting"
        action_log = await tx.write_action_log(flow_id, node_id, action,
                                                result_text, reason, actor,
                                                status="pending")
        # 2. 同事务 + SELECT ... FOR UPDATE 防并发双击
        node_state = await tx.lock_node_state(node_id)
        if node_state.status != "waiting_human":
            raise ConflictError("节点状态已变更")
        # 3. 提交：业务表事务结束
    # 4. 事务外 invoke LangGraph（这一步可能失败）
    try:
        await graph.aupdate_state(
            config={"configurable": {"thread_id": flow_id}},
            values={"current_action": action,
                    "decisions": {node_state.node_name: result_text}},
        )
        await graph.ainvoke(None, config={"configurable": {"thread_id": flow_id}})
    except Exception as e:
        # 5. 失败 → 把 action_log 标 failed + 告警 + 提供 retry 接口
        await db.mark_action_log_failed(action_log.id, str(e))
        await alert_hr("流程推进失败，需手工恢复", flow_id, node_id)
        raise
    # 6. 成功 → action_log 标 confirmed
    await db.mark_action_log_confirmed(action_log.id)
```

- 提供 `scripts/recover_from_db.py`：扫所有 `action_logs.status='failed'`，重新 invoke LangGraph
- 节点函数内**只发通知不做业务写**（通知失败靠 NOTI-04 重试，不阻塞流程）
- 写 e2e 测试：故意让 invoke 抛异常，验证有 retry 路径

**Warning signs:**
- HR Dashboard 看到节点 `status=done` 但 `flow_instances.current_nodes` 还是同一个 ID（没推进）
- 数据库里 `action_logs.status='pending'` 数量 > 0 持续 1 分钟以上
- LangGraph `get_state(thread_id)` 显示 `next=("xxx",)` 但业务表说已 done

**Phase to address:** P2（业务表 + 节点函数双写规范）

---

### Pitfall 3: `interrupt_before` + 重复 `invoke(None)` 死循环 [致命]

**What goes wrong:**
人工节点点了"继续" → API 写完业务表 → `graph.ainvoke(None)` → graph 从 interrupt 处恢复 → 立刻又遇到下一个 interrupt → API 返回 → 前端没拿到结果，用户再点一次"继续" → invoke 同一个 thread_id → 重复执行下游节点函数（重复发邮件！）

**Why it happens:**
1. `interrupt_before` 不会清空 `current_action` 字段，下次 invoke 时下游节点拿到的还是旧 action
2. 没在节点函数里做幂等检查（"我已经发过这个节点的邮件了吗？"）
3. GitHub issue [#7780](https://github.com/langchain-ai/langgraph/issues/7780)：`interrupt()` 在 loop 里会触发"extra resumes"

**How to avoid:**
```python
# 1. update_state 时显式清掉上次 action，避免幽灵决策
await graph.aupdate_state(
    config={"configurable": {"thread_id": flow_id}},
    values={"current_action": action,
            "decisions": {node_state.node_name: result_text}},
)

# 2. 节点函数幂等：进入时先查业务表有没有 "已发通知" 记录
async def manager_review_node(state):
    existing = await state_store.get_node_state(state["flow_id"], "manager_review")
    if existing and existing.status == "waiting_human" and existing.notified_at:
        # 已经发过通知，不要重复发
        return state
    # ... 发邮件 ...

# 3. API 层加幂等：用 (flow_id, node_id, action) 做 dedup key
@router.post("/api/flows/{flow_id}/nodes/{node_id}/actions")
async def submit(...):
    idempotency_key = f"{flow_id}:{node_id}:{action}:{actor}"
    if await redis.set(idempotency_key, "1", nx=True, ex=60) is None:
        raise HTTPException(409, "duplicate submission")
    ...
```

**Warning signs:**
- 演示时一个节点收到 2 封同样邮件
- 单元测试里同一个 `flow_id` 跑两次 invoke 输出不一样
- LangGraph state 里 `decisions` 字典越来越大，里面有旧节点的残留

**Phase to address:** P1（节点函数 + interrupt 设计）+ P3（API 幂等中间件）

---

### Pitfall 4: 并行节点 State Reducer 漏配导致 result_text 互相覆盖 [致命]

**What goes wrong:**
设备归还 / 权限回收 / 知识交接 / 财务结算 4 个并行节点同时完成，最后只有一个的 `result_text` 进了 state，其他 3 个丢了 → 申请人最终确认邮件少了 3 个节点的内容。

**Why it happens:**
LangGraph 的并行节点合并 state 时，**默认对每个 key 是"最后写赢"**（last-write-wins）。如果多个节点同时写 `decisions: {...}` 字段，没用 reducer 就直接覆盖。

**How to avoid:**
```python
from typing import Annotated, TypedDict
from operator import add

# ✅ 用 reducer 合并 dict
def merge_decisions(left: dict, right: dict) -> dict:
    return {**left, **right}

class OffboardingState(TypedDict):
    employee_id: str
    flow_id: str
    decisions: Annotated[dict, merge_decisions]   # 关键：reducer
    node_results: Annotated[list, add]            # 列表用 operator.add 拼接
    current_action: str                            # 单值字段不要并行写
```

或者**走业务表聚合**（更安全）：并行节点不写 LangGraph state 的 `decisions`，只写业务表 `node_states`；扇入节点 `applicant_final_confirm_node` 从 `flow_instances.context.node_results[]` 读取（PRD §4.3.1 已经这么设计了）。

**Warning signs:**
- 申请人最终确认邮件里只有 1-2 个节点的备注，其他全空
- 单测：用 `AsyncMock` 模拟 4 个并行节点都返回不同 `decisions`，断言最后 state 里有全部 4 个 → 失败

**Phase to address:** P1（StateGraph 定义 + reducer 校验）

---

### Pitfall 5: Checkpoint 序列化失败（state 含 datetime / Decimal / Pydantic v2 model）[致命]

**What goes wrong:**
节点函数返回 state 里塞了 `datetime.now()` / `Decimal("100.5")` / SQLAlchemy ORM object → `PostgresSaver` 用 `msgpack` 序列化时抛 `TypeError: Object of type datetime is not JSON serializable` 或安静地把对象变成 `null`，恢复时拿到坏数据。

**Why it happens:**
LangGraph 默认 serializer 是 msgpack（2026 起更严格：`LANGGRAPH_STRICT_MSGPACK=true` 限制只能序列化已知类型，防 RCE）。datetime / Decimal / 自定义类不在白名单。

**How to avoid:**
**规则：LangGraph state 只放原始类型**（str / int / float / bool / list / dict）。

```python
# ❌ 别这样
state["entered_at"] = datetime.now()
state["salary"] = Decimal("12000.50")
state["employee"] = await db.get_employee(...)   # SQLAlchemy model

# ✅ 这样
state["entered_at_iso"] = datetime.now().isoformat()   # ISO 字符串
state["salary_cents"] = 1200050                         # int
state["employee_id"] = employee.id                      # 只存 ID，需要时业务表查
```

**Pydantic v2 model** 必须 `.model_dump(mode="json")` 后再放 state。

**测试时**：写一个 `test_state_serializable.py`，对每个节点的返回 state 跑 `msgpack.packb(...)`，不抛异常才算过。

**Warning signs:**
- pytest fixture 报 `cannot pickle '_thread.lock' object` 或 `TypeError: Object of type X is not JSON serializable`
- 重启后 `graph.get_state(thread_id)` 拿到 dict 里某些字段是 `None`（被静默丢弃）
- `LANGGRAPH_STRICT_MSGPACK=true` 启用后启动直接报错

**Phase to address:** P1（StateGraph 定义 + state schema 校验）

---

### Pitfall 6: JWT 双击 race condition（jti 黑名单时序漏洞）[致命] [演示场景高发]

**What goes wrong:**
演示者在邮件客户端**双击**了"立即处理"按钮 → 浏览器开了 2 个 tab，几乎同时 `POST /api/auth/exchange` → 两个请求都通过了 jti 校验（黑名单还没写入）→ 都签发了 cookie → 第二个 session 把第一个挤掉。

**Why it happens:**
- "校验 jti 未消费" 和 "写 jti 到黑名单" 不是原子的
- Redis `GET` 然后 `SET` 之间有 race window（毫秒级也能命中）

**How to avoid:**
```python
# 用 Redis SETNX 原子操作（PRD §6.2.2 步骤 2/5 必须合并）
async def exchange_token(token: str):
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    jti = payload["jti"]
    # ✅ SET ... NX EX：原子的 "如果不存在就设置"
    consumed = await redis.set(f"jti:{jti}", "consumed",
                                nx=True, ex=86400)
    if consumed is None:
        raise HTTPException(401, "token 已使用")
    # ... 后续签 cookie ...
```

不要用 `if await redis.get(f"jti:{jti}"): raise; await redis.set(...)` 这种两步操作。

**Warning signs:**
- 用 `pytest-asyncio` + `asyncio.gather` 同时发 2 个 exchange 请求 → 应该一个 200 一个 401，若都 200 = 有 race
- 演示时 "我点了一下怎么登录的是上一个角色"

**Phase to address:** P3（鉴权 + 深链）

---

### Pitfall 7: Mattermost Interactive Message 按钮在内网无响应（AllowedUntrustedInternalConnections 没配）[致命]

**What goes wrong:**
Mattermost 推了卡片消息，用户点"继续 / 退回 / 拒绝"按钮 → 没反应 → Mattermost server log 里有 `err=address forbidden`。整个 IM 通道哑火，但邮件还能用所以演示者可能演到一半才发现。

**Why it happens:**
Mattermost 默认禁止 Bot/Webhook callback URL 指向内网地址（防 SSRF）。本项目的 callback URL 是 `http://flow-api:8000/api/action/...`（docker 内网）或 `http://192.168.2.44:8000/...`（私网 IP），都被默认黑名单拦掉。

**How to avoid:**
Mattermost 管理员后台 → System Console → Environment → Developer → "Allow untrusted internal connections to" 配置：

```
192.168.2.44 flow-api localhost 127.0.0.1
```

或者 `config.json`：
```json
{
  "ServiceSettings": {
    "AllowedUntrustedInternalConnections": "192.168.2.44 flow-api localhost"
  }
}
```

环境变量形式：`MM_SERVICESETTINGS_ALLOWEDUNTRUSTEDINTERNALCONNECTIONS="192.168.2.44 flow-api localhost"`

**部署 checklist 必加一条**：seed 脚本启动时调 `GET /api/v4/config/client` 校验该字段非空，否则报错退出。

**Warning signs:**
- Mattermost server log（`/opt/mattermost/logs/mattermost.log`）出现 `address forbidden` 或 `webhook target IP is internal`
- 卡片按钮转圈 → 报红 "Pretext failed" / "Server error"

**Phase to address:** P4（Mattermost 集成 + Seed 脚本健康检查）

---

### Pitfall 8: 密钥提交到 git（`.env` 没在 .gitignore / `docker-compose.yml` 硬编码）[致命]

**What goes wrong:**
- `JWT_SECRET` / `QQ_SMTP_AUTH_CODE` / `MM_BOT_TOKEN` / `GLM_API_KEY` 写进 `.env` 后 commit → 推到 `git@github.com:LaiosOvO/liuxin-interview.git`（public 仓库）→ QQ 邮箱被滥用、Mattermost Bot 被劫持
- 或者直接写进 `docker-compose.yml` / `PROJECT.md` 截图分享时泄露

**Why it happens:**
新建项目时容易忘记设 `.gitignore`；演示项目"反正是测试号"心态。

**How to avoid:**
**P1 第一个 commit 之前必做**：

```bash
# .gitignore 必含
.env
.env.local
.env.*.local
*.key
*.pem
.envrc
```

```bash
# .env.example 只放 key 名 + 占位符
JWT_SECRET=__please_generate__
QQ_SMTP_AUTH_CODE=__16_chars_qq_auth_code__
MM_BOT_TOKEN=__mattermost_personal_access_token__
GLM_API_KEY=__zhipu_api_key__
```

```yaml
# docker-compose.yml 用 env_file 引用，不直接写值
services:
  flow-api:
    env_file: .env
    environment:
      JWT_SECRET: ${JWT_SECRET}   # 从 shell env 读，不写值
```

**Pre-commit hook** 装 `gitleaks` 或 `detect-secrets`：
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks: [{id: gitleaks}]
```

**JWT_SECRET 生成**：`openssl rand -hex 32` → 32 字节随机串，不要用 `"secret"` / `"changeme"`。

**如果已经泄露**：立刻 (1) 在 QQ 邮箱重置授权码 (2) Mattermost 重新生成 Bot Token (3) 用 `git filter-repo` 从历史里抹掉，强推 (4) 假设 LLM API 已被刷，联系智谱重置 key

**Warning signs:**
- `git log -p | grep -i "smtp_password\|jwt_secret\|api_key"` 出现真值
- GitHub Secret Scanning 告警邮件
- QQ 邮箱告警 "异地登录" / "频繁发送"

**Phase to address:** P1（项目初始化 + .gitignore + pre-commit）

---

### Pitfall 9: Docker Compose `down -v` 误删 Postgres 数据卷 [致命] [演示场景高发]

**What goes wrong:**
演示前一晚跑 `docker compose down -v` 清空环境重新 seed，第二天发现连之前 seed 的 demo 用户都没了；或者更糟，演示中途想"重启一下服务"打了 `down -v`，Postgres 数据 + LangGraph checkpoint 全没。

**Why it happens:**
`-v` 标志删除所有 named volume，包括 `postgres_data`。`down` 不带 `-v` 只停容器保留卷，新手分不清。

**How to avoid:**
1. **写两个脚本** 强约束语义：
```bash
# scripts/dev-restart.sh —— 只重启，不删数据
docker compose restart flow-api nginx

# scripts/dev-reset.sh —— 明确的"清空一切"
read -p "⚠️  将删除所有数据（postgres + redis + checkpoint），输入 RESET 确认: " ans
[ "$ans" = "RESET" ] || exit 1
docker compose down -v
docker compose up -d
docker compose exec flow-api python scripts/seed_demo_data.py
```

2. **生产环境** 加 `external: true` 让 volume 不受 compose 控制：
```yaml
volumes:
  postgres_data:
    external: true   # 必须手工 docker volume create postgres_data 创建
```

3. **演示前 backup**：
```bash
docker compose exec -T postgres pg_dump -U flow flow_db > backup-$(date +%F).sql
```

**Warning signs:**
- `docker volume ls` 看不到 `liuxin_postgres_data`
- seed 完后 Postgres 里 `users` 表为空

**Phase to address:** P6（部署 + 运维脚本）

---

### Pitfall 10: 演示模式忘记加角色前缀 / 演示模式没切回 prod 上线 [致命] [DEMO-ONLY]

**What goes wrong:**
- 演示模式下 8 个角色邮件都发到 `1624456575@qq.com`，但发件代码忘了加 `[角色·username]` 主题前缀 → 演示者收到 8 封"离职流程通知"主题完全一样，分不清当前应该扮演谁
- 演示完上线生产，`APP_MODE` 还是 `demo` → 真实用户的离职邮件全部被覆写到 `DEMO_INBOX`，真实 assignee 永远收不到通知

**Why it happens:**
PRD §7.4.1 设计了角色前缀，但实现时只在邮件主题里加，正文 / 链接 / cookie 里没区分；或者覆写逻辑写在 SMTP client 而不是 dispatcher，难以审计。

**How to avoid:**
```python
# backend/app/notification/sender.py
@dataclass
class EmailEnvelope:
    """显式的发件信封，演示 / 生产差异在这里收口"""
    real_recipient: str       # notifications 表存这个（审计真相）
    delivery_to: str          # 实际投递地址（demo 模式覆写为 DEMO_INBOX）
    subject: str              # demo 模式自动加 [角色·username]
    role: str
    username: str
    body_html: str

def build_envelope(node_state, settings) -> EmailEnvelope:
    real = node_state.assignee_email
    if settings.APP_MODE == "demo":
        delivery = settings.DEMO_INBOX
        subject = f"[{ROLE_CN[node_state.role]}·{node_state.assignee_username}] "
                  f"{base_subject(node_state)}"
        body = DEMO_BANNER.format(real_to=real) + render_body(node_state)
    else:
        delivery = real
        subject = base_subject(node_state)
        body = render_body(node_state)
    return EmailEnvelope(real_recipient=real, delivery_to=delivery,
                          subject=subject, role=node_state.role,
                          username=node_state.assignee_username, body_html=body)
```

**生产切换 checklist**：
- [ ] `.env` 里 `APP_MODE=prod`
- [ ] 启动时 log 一行 `APP_MODE=prod, DEMO_INBOX ignored`，prod 模式必须有此日志
- [ ] 健康检查接口 `/api/health` 返回 `{"mode": "prod", ...}`，前端 footer 显示 mode
- [ ] 加测试：`APP_MODE=prod` 下 `delivery_to == real_recipient`

**Warning signs:**
- 演示时收件箱 8 封邮件主题分不开
- 上线后真实用户反馈"没收到邮件"，HR 邮箱里却堆满"离职流程通知"

**Phase to address:** P4（通知 + 演示模式实现）+ P6（上线 checklist）

---

### Pitfall 11: Seed 脚本不幂等，演示前必须 reset 才能跑 [致命] [DEMO-ONLY]

**What goes wrong:**
`seed_demo_data.py` 第二次执行抛 `IntegrityError: duplicate key value violates unique constraint "users_username_key"` 或 Mattermost 返回 `403: username already exists` → 必须先 `dev-reset.sh` 才能再跑，演示前抢救成本高。

**Why it happens:**
新手写 seed 用 `INSERT INTO ...`，不用 `INSERT ... ON CONFLICT DO UPDATE`；Mattermost API 调用没先 `GET /users/username/{name}` 检查存在。

**How to avoid:**
```python
# scripts/seed_demo_data.py
async def ensure_team(client, team_name, display_name):
    """幂等创建 team"""
    existing = await client.get(f"/api/v4/teams/name/{team_name}")
    if existing.status_code == 200:
        return existing.json()
    resp = await client.post("/api/v4/teams", json={
        "name": team_name, "display_name": display_name, "type": "O",
    })
    resp.raise_for_status()
    return resp.json()

async def ensure_user(client, username, email, password, **attrs):
    existing = await client.get(f"/api/v4/users/username/{username}")
    if existing.status_code == 200:
        # 更新 custom attributes（即使已存在也要同步最新值）
        user = existing.json()
        await sync_custom_attrs(client, user["id"], attrs)
        return user
    resp = await client.post("/api/v4/users", json={
        "username": username, "email": email, "password": password,
    })
    resp.raise_for_status()
    user = resp.json()
    await sync_custom_attrs(client, user["id"], attrs)
    return user

# 业务表也用 upsert
await db.execute(text("""
    INSERT INTO users (id, username, email, role, manager_email)
    VALUES (:id, :username, :email, :role, :manager_email)
    ON CONFLICT (username) DO UPDATE SET
        email = EXCLUDED.email,
        role = EXCLUDED.role,
        manager_email = EXCLUDED.manager_email
"""), params)
```

**强制测试**：CI 里跑 seed 两次，第二次必须 0 错误。

**Warning signs:**
- `python scripts/seed_demo_data.py && python scripts/seed_demo_data.py` 第二次失败

**Phase to address:** P4（Seed 脚本）

---

## Moderate Pitfalls（改进：能演示但 demo 体验差 / 中等隐患）

### Pitfall 12: HttpOnly Cookie 在 HTTP 内网下 Secure flag 处理错误

**What goes wrong:**
开发时为了"安全"给 cookie 加 `Secure=True` flag → 部署到 `http://192.168.2.44`（HTTP，无证书）→ 浏览器拒绝设置 cookie → 一键登录后立刻被踢回登录页。

**Why it happens:**
`Secure` flag 要求 HTTPS（localhost 除外）；内网 HTTP 部署不能开。

**How to avoid:**
```python
# backend/app/auth/cookie.py
def set_session_cookie(response, token, settings):
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=(settings.APP_MODE == "prod" and settings.HTTPS_ENABLED),
        samesite="lax",   # 不要 strict，否则邮件链接跨站跳转失效
        max_age=86400,
        path="/",
    )
```

`SameSite=Lax` 是关键：邮件客户端点链接进浏览器算 cross-site GET，Strict 会丢 cookie。

**Phase to address:** P3（鉴权 cookie 配置）

---

### Pitfall 13: Token 出现在 URL 里，浏览器历史 / nginx access log / proxy 泄露

**What goes wrong:**
深链格式 `?token=eyJhbGc...`（PRD §6.2 现状），token 进了：
- 浏览器历史记录（任何人能从历史复制 URL）
- nginx access.log（运维 / 入侵者可读）
- Mattermost 链接预览 fetch 时把 token 带给了第三方

**Why it happens:**
为了"邮件一键登录"必须在 URL 携带 token，难以完全避免。

**How to avoid（缓解，非根治）:**
1. **token 一次性** + **短 TTL**（24h 偏长，建议 2-4h）
2. nginx 配置 **不记录 query string**：
```nginx
log_format access_no_query '$remote_addr - $request_method $uri '
                            '"$http_referer" "$http_user_agent"';
access_log /var/log/nginx/access.log access_no_query;
```
3. 收到 token 后立刻 **redirect 到无 token URL**：
```python
# /api/auth/exchange 返回 redirect_to: /flow/.../node/...（不带 token）
# 前端用 router.replace() 而非 push()，从历史里清掉带 token 的 URL
```
4. **Mattermost 卡片** 用 `actions` callback 而不是 `title_link` 跳转，token 不进 URL bar

**Warning signs:**
- `tail -f /var/log/nginx/access.log | grep "token="` 看到 token
- 浏览器历史 Ctrl+H 看到带 token 的 URL

**Phase to address:** P3（鉴权 + URL 设计）+ P6（nginx log 配置）

---

### Pitfall 14: QQ SMTP 反垃圾邮件触发（频率限制 / 主题被标 spam）

**What goes wrong:**
演示时连续触发 8 封邮件 → QQ SMTP 返回 `550 Ip frequency limited` → 邮件全部失败 → 演示卡死。或者邮件被 QQ 邮箱直接进垃圾箱，演示者翻不到。

**Why it happens:**
QQ SMTP 有未公开的频率限制：每分钟 / 每小时 / 每天分别限流，超了封 IP。重复主题、含链接、HTML 邮件容易触发 spam 判定。

**How to avoid:**
1. **演示前预热**：演示前 1 小时手工触发 1 封测试邮件，确认 QQ 没限流
2. **节流发送**：dispatcher 加 `asyncio.Semaphore(2)` + 邮件之间 sleep 1s，避免并发突发
3. **主题不重复**：每封邮件带 `{employee_name} {timestamp}` 让 spam 引擎认为是新对话
4. **正文**：避免大段链接、避免全英文、加上下文化的真实人名
5. **失败 fallback**：QQ 拒绝时自动写 `notifications.status=failed`，Mattermost 继续推送（双通道存在的意义）
6. **演示备份方案**：本地起一个 [MailHog](https://github.com/mailhog/MailHog)，`APP_MODE=demo_local` 走 MailHog，QQ 限流时切到本地

**Warning signs:**
- SMTP log `550 Sender frequency limited` / `550 Ip frequency limited`
- 演示邮箱里前 2 封正常，后面收不到

**Phase to address:** P4（通知 + 限流 + 失败重试）

---

### Pitfall 15: 中文邮件主题编码（不做 RFC 2047 / base64 编码）

**What goes wrong:**
中文主题 `[设备管理员·it.charlie] 张三 设备归还待处理` 在某些客户端显示为 `=?utf-8?B?...?=` 原始编码，或者乱码 `??` `???`。

**Why it happens:**
SMTP 协议要求 header 是 ASCII；非 ASCII 必须 RFC 2047 编码（`=?utf-8?B?{base64}?=`）。`aiosmtplib` + `email.message.EmailMessage` 默认会处理，但用 `MIMEText` + 手写 `msg['Subject'] = "中文"` 不一定会。

**How to avoid:**
```python
from email.message import EmailMessage
from email.headerregistry import Address

msg = EmailMessage()
msg["Subject"] = subject   # EmailMessage 会自动编码，不要手写 MIMEText
msg["From"] = Address(display_name=settings.SMTP_FROM_NAME,
                       addr_spec=settings.SMTP_USER)
msg["To"] = envelope.delivery_to
msg.set_content(text_body)
msg.add_alternative(html_body, subtype="html")
# aiosmtplib 直接发 msg，不要自己 str(msg)
await aiosmtplib.send(msg, hostname=..., port=465, use_tls=True, ...)
```

**Warning signs:**
- 邮件客户端主题显示 `=?utf-8?B?W+iuvuWkh+euoeeQhuWRmF0=?=`
- iOS Mail 没问题但 Outlook 乱码（说明 base64 没做）

**Phase to address:** P4（邮件渲染 + 编码）

---

### Pitfall 16: 节点函数副作用 vs LangGraph 回退（已发邮件但流程回退了）

**What goes wrong:**
HR 终审节点 `return` 退回到"设备归还"节点 → LangGraph 重新执行 `device_return_node` → 又给 IT 发了一封同样的邮件 → IT 收到重复通知一脸懵。

**Why it happens:**
LangGraph 的"回退"实际上是回到该节点函数重新执行；函数内的副作用（发邮件）每次都触发。

**How to avoid:**
节点函数发通知前检查"这次进入是新激活还是 retry"：

```python
async def device_return_node(state):
    node_state = await state_store.get_or_create_node_state(
        flow_id=state["flow_id"], node_name="device_return"
    )
    # 通过业务表的 entered_at 判断：本次进入是不是新激活
    is_first_entry = node_state.entered_at is None
    if is_first_entry:
        await state_store.activate_node(node_state.id)
        await notification_dispatcher.dispatch(node_state, channels=["email", "mattermost"])
    else:
        # 已经激活过（比如 graph 回退到这里）→ 只发"重新激活提醒"
        await notification_dispatcher.dispatch(
            node_state, channels=["email"], template="reactivated"
        )
    return state
```

或者，**回退路径不重发邮件**：用 LangGraph 的条件边 + state 字段区分"首次激活" vs "退回激活"，不同分支调用不同节点。

**Warning signs:**
- 演示中"退回"后责任人吐槽"我刚处理完又收到一封"
- `notifications` 表同一个 `(flow_id, node_id, recipient)` 有 ≥ 2 条记录

**Phase to address:** P2（节点函数 + 业务表幂等设计）

---

### Pitfall 17: thread_id 重用导致状态污染

**What goes wrong:**
为了"快速重跑"用同一个 `flow_id` (= LangGraph thread_id) 再起一次流程 → LangGraph 看到 checkpoint 已存在，从上次中断处恢复 → state 里全是上次的 decisions → 流程行为完全错乱。

**Why it happens:**
PRD 用 `flow_id` 作为 `thread_id`（PRD §5.3.1 示例）。重用就是 bug。

**How to avoid:**
- **每次新流程必须新 UUID**：`flow_id = uuid4()`；演示重跑就生成新 ID
- 演示场景如果想"重置某个流程"，提供 `scripts/reset_flow.py <flow_id>` 同时删 LangGraph checkpoint + 业务表记录
- 不要在 URL 里允许传 `?flow_id=xxx` 让用户能复用

**Warning signs:**
- 新流程一开始就跳到中间节点
- LangGraph `get_state` 显示 `decisions` 里有不该有的旧节点

**Phase to address:** P1（flow 创建 API 设计）

---

### Pitfall 18: Mattermost Bot Token 权限不足（Member vs Admin）

**What goes wrong:**
Bot 账号是 Member 角色 → `POST /api/v4/users`（创建用户）返回 `403 Forbidden` → seed 脚本失败。

**Why it happens:**
Mattermost Bot 默认 Member 权限，能发消息但不能管理用户。

**How to avoke:**
- Seed 脚本用 **System Admin** 的 Personal Access Token（不是 Bot Token）
- 运行时通知用 **Bot Token**（最小权限）
- `.env` 里区分：
```env
MM_ADMIN_TOKEN=${MM_ADMIN_PAT}        # seed 时用，跑完可以注释掉
MM_BOT_TOKEN=${MM_BOT_PAT}            # 运行时用
```
- Seed 脚本启动校验：`GET /api/v4/users/me` 返回的 `roles` 必须含 `system_admin`

**Phase to address:** P4（Mattermost 集成 + seed）

---

### Pitfall 19: Next.js 静态导出动态路由缺 `generateStaticParams` build 失败

**What goes wrong:**
`/flow/[flow_id]/node/[node_id]` 这种动态路由在 `output: 'export'` 模式下 build 报：
```
Error: Page "/flow/[flow_id]/node/[node_id]" is missing exported function "generateStaticParams()".
```

**Why it happens:**
Next.js 15 静态导出要求所有动态路由在 build 时知道所有可能的参数值。但本项目的 `flow_id` 是运行时生成的 UUID，build 时不知道。

**How to avoid:**
返回空数组 + 设置 `dynamicParams = true`：

```typescript
// app/flow/[flow_id]/node/[node_id]/page.tsx
export async function generateStaticParams() {
  return [];   // build 时不生成任何具体页，全靠运行时 CSR
}

export const dynamicParams = true;   // 允许运行时未知 params

// 页面 100% 客户端渲染
'use client';
import { useParams } from 'next/navigation';

export default function NodePage() {
  const { flow_id, node_id } = useParams<{flow_id: string, node_id: string}>();
  // useEffect fetch /api/...
}
```

**关键**：`output: 'export'` 模式下 `useParams()` 在客户端可用，但 `params` prop（Next 15 是 Promise）在静态壳页不能 await，必须用 `'use client'` + `useParams`。

**Warning signs:**
- `pnpm build` 报 `generateStaticParams is missing`
- 或 build 通过但访问 `/flow/abc/node/def` 返回 404

**Phase to address:** P5（前端动态路由 + 静态导出）

---

### Pitfall 20: nginx `location /` 吞掉 `location /api/`

**What goes wrong:**
浏览器请求 `/api/flows/xxx` → nginx 返回前端 `index.html` → 前端拿到 HTML 当 JSON 解析报错。

**Why it happens:**
nginx `location` 匹配优先级：精确 `=` > 前缀 `^~` > 正则 `~` > 普通前缀。普通前缀按**最长匹配**，但 `location /` 是 fallback。如果 `location /` 写在前面或写错，会拦截 API。

**How to avoid:**
PRD §10.0.2 的配置正确，但要加 `^~` 让 `/api/` 不被正则吞掉：

```nginx
location ^~ /api/ {
    proxy_pass http://flow-api:8000;
    # ... 其他 proxy header
}

location ^~ /ws/ {
    proxy_pass http://flow-api:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
}

location / {
    root /usr/share/nginx/html;
    try_files $uri $uri.html $uri/index.html /index.html;
}
```

**校验命令**：
```bash
curl -i http://192.168.2.44/api/health        # 必须 Content-Type: application/json
curl -i http://192.168.2.44/                  # 必须 Content-Type: text/html
curl -i http://192.168.2.44/flow/abc/node/xxx # 也必须 text/html（SPA fallback）
```

**Phase to address:** P6（nginx 配置）

---

### Pitfall 21: 容器间 DNS 不通 / 端口冲突（Mattermost 已占 8065）

**What goes wrong:**
- `flow-api` 容器里访问 `http://192.168.2.44:8065/api/v4/users`（Mattermost 在宿主机）→ Docker 网络模式不对 → 不通
- Mattermost 已部署在宿主机 `:8065`，本项目 docker-compose 又起了一个 `:8065` 端口 → 端口冲突起不来

**Why it happens:**
Mattermost 不在 docker-compose 里（已部署在宿主机），但 docker network 默认无法访问宿主机 IP。

**How to avoid:**
1. **bridge 网络 + extra_hosts**：
```yaml
services:
  flow-api:
    extra_hosts:
      - "host.docker.internal:host-gateway"   # Linux 也支持（Docker 20.10+）
    environment:
      MATTERMOST_URL: http://host.docker.internal:8065
```
2. **或者直接用宿主机 IP** `http://192.168.2.44:8065` 并确认 Docker bridge 默认能出宿主机网络（Linux 默认能）
3. **端口规划**（避免冲突）：
| 端口 | 服务 | 来源 |
|------|------|------|
| 80 | nginx | 本项目 |
| 5432 | postgres | 本项目（仅容器间，不映射宿主） |
| 6379 | redis | 本项目（仅容器间） |
| 8000 | flow-api | 本项目（仅容器间，nginx 反代） |
| 8065 | Mattermost | 宿主机预先部署 |
| 3000 | （历史 next dev） | **本项目不占用**（静态导出后由 nginx 80 提供） |

注意 PRD §10.1 写的 `DEEPLINK_BASE_URL=http://192.168.2.44:3000` 是**错的**，nginx 在 80 端口，深链应该是 `http://192.168.2.44`（无端口或 :80）。

**Warning signs:**
- `docker compose up` 报 `bind: address already in use`
- 容器内 `curl http://192.168.2.44:8065/api/v4/users/me` 超时
- 演示者点深链跳转到 :3000 → 浏览器报"无法连接"

**Phase to address:** P6（部署 + docker network） + 修正 PRD DEEPLINK_BASE_URL

---

### Pitfall 22: LLM API 调用阻塞流程（演示中卡 30 秒）

**What goes wrong:**
申请人最终确认节点调 GLM 生成摘要 → GLM API 偶尔 timeout 60s → 整个邮件没发出 → 申请人没收到邮件 → 流程卡在 `applicant_final_confirm` interrupt。

**Why it happens:**
LLM-02 设计为"在邮件正文加摘要"，开发者直接 `summary = await glm.complete(...)` 同步等返回，没设置超时/降级。

**How to avoid:**
PRD LLM-03 已经说"失败不阻塞流程降级为不带摘要的原始版本"，落地：

```python
async def generate_summary_with_fallback(node_results, timeout=8.0) -> str:
    try:
        async with asyncio.timeout(timeout):
            return await glm.summarize(node_results)
    except (asyncio.TimeoutError, GLMError) as e:
        logger.warning(f"LLM 摘要失败，降级到原文: {e}")
        return ""   # 空字符串，模板里 if summary 决定是否展示
```

演示当天 **先预热**：演示前 5 分钟跑一次 GLM 测试调用，确认服务可用。

**Phase to address:** P4（通知 + LLM 集成）

---

### Pitfall 23: 异步测试 fixture scope / event loop 冲突

**What goes wrong:**
`pytest-asyncio` 默认 `function` scope event loop，`AsyncPostgresSaver` 用 `session` scope 起的 pool → loop 已关闭报 `RuntimeError: Event loop is closed`。

**Why it happens:**
异步资源（pool / saver / FastAPI app）和 test fixture scope 必须匹配同一个 loop。

**How to avoid:**
```python
# tests/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# 锁定 session scope event loop
@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()

@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def db_pool():
    pool = await create_pool(TEST_DSN)
    yield pool
    await pool.close()

@pytest_asyncio.fixture(loop_scope="session")
async def client(db_pool):
    async with AsyncClient(transport=ASGITransport(app=app),
                            base_url="http://test") as c:
        yield c
```

注意 `pytest-asyncio >= 0.23` 用 `loop_scope` 参数（不是 `event_loop` fixture 覆盖）。

**Warning signs:**
- `RuntimeError: Event loop is closed`
- `Future attached to a different loop`

**Phase to address:** P1（测试基础设施）

---

## Minor Pitfalls（次要：影响小或事后好修）

### Pitfall 24: HTML 邮件按钮在不同客户端样式崩坏

**What goes wrong:**
QQ 邮箱 Web 版按钮正常，Outlook / Foxmail 按钮变成纯文本链接。

**Prevention:**
- 用 [MJML](https://mjml.io/) 或 [django-anymail](https://github.com/anymail/django-anymail) 风格的 table-based HTML（不用 div/flex）
- 按钮用 `<a>` 包 `<table>`，inline style，不要 `<button>`
- 测试矩阵：QQ 邮箱 Web + iOS Mail + Outlook + Foxmail，每个客户端截图保存

```html
<table cellspacing="0" cellpadding="0" border="0" align="center">
  <tr><td bgcolor="#0066cc" style="border-radius:4px;">
    <a href="{deep_link}"
       style="display:inline-block;padding:12px 24px;color:#ffffff;
              text-decoration:none;font-weight:bold;">
      立即处理
    </a>
  </td></tr>
</table>
```

**Phase to address:** P4

---

### Pitfall 25: Checkpoint 表无清理导致 Postgres 持续膨胀

**What goes wrong:**
跑了 1000 个演示流程 → `checkpoint_blobs` 表 50GB → 数据库慢。

**Prevention:**
- 演示环境定期跑 `DELETE FROM langgraph.checkpoints WHERE created_at < NOW() - INTERVAL '7 days'`
- 写 `scripts/cleanup_old_checkpoints.py`
- LangGraph 0.2+ 支持 `saver.adelete_thread(thread_id)`，流程归档后调一次

**Phase to address:** P6（运维）

---

### Pitfall 26: webhook 签名验证遗漏（Mattermost 双向）

**What goes wrong:**
Mattermost 卡片按钮 callback `POST /api/action/...` 不校验来源 → 任何人 curl 都能伪造决策。

**Prevention:**
Mattermost Interactive Message 在 `request_id` / `trigger_id` 里带签名信息，FastAPI 接收时校验：
```python
def verify_mattermost_origin(request_body, headers):
    # Mattermost 不像 Slack 用 HMAC，但带 token 字段，校验等于配置的 webhook token
    if request_body.get("token") != settings.MM_WEBHOOK_TOKEN:
        raise HTTPException(401)
```
最简方案：callback URL 加 query param `?secret=xxx`（仅内网用，作为额外验证）

**Phase to address:** P4

---

### Pitfall 27: 演示中 token 过期 / session 切换角色

**What goes wrong:**
演示者上午演到一半午饭，下午回来 cookie 过期 → 点深链发现 token 也过期 → 演示中断。

**Prevention:**
- 演示场景把 `TOKEN_EXPIRY_HOURS=24` 调到 `72`（仅 demo）
- 提供 "重发当前节点通知" 按钮 → `POST /api/notifications/{id}/resend` 生成新 token
- 演示前最后一次完整跑通 → 不要演示间隔 > 24h

**Phase to address:** P5（HR Dashboard 加 resend 按钮）

---

### Pitfall 28: 演示前没清空数据库

**What goes wrong:**
昨天测试的脏数据 → 演示时 HR Dashboard 显示一堆历史失败流程 → 影响观感。

**Prevention:**
演示 checklist 第一步：
```bash
./scripts/dev-reset.sh && ./scripts/seed_demo_data.py
# 确认 HR Dashboard 只有 1 个 demo 流程
curl http://192.168.2.44/api/flows | jq 'length'   # 应该是 1
```

**Phase to address:** P6（演示 runbook）

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| 流程模板硬编码 Python（不做编排 UI） | 1-2 天产出 demo | v2 想改流程要发版 | ✅ v1 演示项目（PRD 已采纳）|
| 节点函数同步调 SMTP（不走 Celery / 队列） | 少一个组件 | 发件慢时阻塞 API 线程 | ✅ demo（用 fastapi BackgroundTasks 即可），prod 必须改异步队列 |
| 用 Redis 做 jti 黑名单（不持久化） | 简单 | redis 重启黑名单丢，旧 token 复活 | ⚠️ demo OK；prod 必须 `appendonly yes` + 同时写 DB `consumed_tokens` 兜底 |
| 业务表用单一 `payload JSONB`（不结构化）| schema 不用频繁迁移 | 查询 / 索引困难 | ✅ v1，v2 按需要 promote 成列 |
| 静态前端（无服务端） | 部署只要 nginx | RSC / API routes 都不能用 | ✅ 本项目（PRD 已采纳），不接受拉回 Node 容器 |
| LLM 摘要同步阻塞节点函数 | 实现简单 | 一次 timeout 卡流程 | ❌ Never — 必须 timeout + 降级 |
| `.env` 真值进 git "反正是测试号" | 部署省事 | 凭证泄露 | ❌ Never |
| 不写测试先跑通 demo | 进度快 | 演示中 bug 难定位 | ⚠️ 仅最初 1-2 天搭骨架可接受，进入 P2 必须 TDD |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **LangGraph PostgresSaver** | 忘记 `await saver.setup()` / 不设 `autocommit=True` | 启动时调 setup；用 `AsyncConnectionPool` + `kwargs={"autocommit": True, "row_factory": dict_row}` |
| **LangGraph 并行节点** | 多节点写同一 state 字段无 reducer | 用 `Annotated[dict, merge_decisions]` 或走业务表聚合 |
| **PostgreSQL（业务 + checkpoint 同库）** | 不分 schema → 表名冲突可能 | `CREATE SCHEMA langgraph`，PostgresSaver 用 langgraph schema，业务表在 public |
| **Mattermost Interactive Buttons** | callback URL 是内网地址，被 SSRF 防护拦 | `AllowedUntrustedInternalConnections` 配置 + seed 启动校验 |
| **Mattermost Bot Token** | 用 Bot Token 调创建用户 API（权限不够） | seed 用 System Admin PAT，运行时用 Bot Token |
| **Mattermost Custom Attributes** | 默认未开启 → 设置字段失败 | 管理员后台 → Site Configuration → Customization → Enable Custom Profile Attributes |
| **QQ SMTP** | 用 STARTTLS / 用登录密码 | 必须 SSL on 465 + 授权码（不是密码） |
| **QQ SMTP 频率** | 演示中连发 8 封被限流 | dispatcher 节流 1 req/s，主题不重复，邮件之间 sleep |
| **JWT 一次性 token** | `if not in blacklist: add to blacklist`（race） | Redis `SET nx ex` 原子操作 |
| **HttpOnly Cookie** | 内网 HTTP 设 Secure flag → 浏览器拒绝 | `secure=(APP_MODE=="prod" and HTTPS_ENABLED)` |
| **Next.js export** | dynamic route 没写 generateStaticParams | 返回 `[]` + `dynamicParams=true` + 客户端 `useParams` |
| **Next.js export** | 用 Server Components 调 API | 全部 `'use client'` + `fetch`；export 模式不能 SSR |
| **Docker network → 宿主机服务** | flow-api 调 `localhost:8065` 不通 | `host.docker.internal` + `extra_hosts: host-gateway` |
| **Nginx SPA fallback** | `location /` 写在 `location /api/` 前面或漏 `^~` | `location ^~ /api/` 优先匹配 + `try_files ... /index.html` 兜底 |
| **GLM API** | 同步等返回阻塞流程 | `asyncio.timeout(8)` + 降级到无摘要 |
| **Postgres async pool** | 用 PgBouncer transaction mode + prepared statements | `prepare_threshold=0` 禁用 prepared，或 PgBouncer 用 session mode |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Checkpoint 表无 GC | Postgres 持续膨胀，查询变慢 | 流程归档后 `saver.adelete_thread(thread_id)`；定时清理脚本 | 1000+ 流程 / 100MB+ checkpoint 表 |
| 节点函数同步 SMTP | 一封慢邮件阻塞下一个节点 | `BackgroundTasks` 或队列异步发 | 并行 4 节点 + 单封邮件 > 3s |
| 大对象进 state | checkpoint 表每步翻倍写入 | state 只存 ID，大对象走业务表 | state size > 100KB |
| 不分 LangGraph schema | 备份 / 迁移业务表时被 checkpoint 表拖累 | 业务表 `public`，checkpoint `langgraph` schema | 项目走到 v2 想做数据治理 |
| Mattermost 卡片消息每节点重发 | 演示频道刷屏 | Bot 推私聊（DM）+ 节流 | 演示给观众看时若推到公开频道 |

> **本项目预期 scale**：演示 < 10 并发流程，prod 假想 < 100/day。绝大多数性能 trap 在这个量级不会爆，但 checkpoint 膨胀和 LLM 阻塞要现在就规避。

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| `.env` 真值进 git | API key / SMTP 凭证泄露被滥用 | `.gitignore` + pre-commit `gitleaks` + `.env.example` 占位符 |
| JWT_SECRET 用 "secret" / 默认值 | 任何人能伪造 token 一键登录任何角色 | `openssl rand -hex 32`；启动时校验长度 ≥ 32 |
| URL 含 token 进 nginx access.log | 日志泄露 = 任何人能复用未消费的 token | nginx `log_format` 不含 query string |
| Cookie 无 SameSite | CSRF 攻击 | `SameSite=Lax`（Strict 会丢邮件链接 cookie） |
| 邮件深链按 GET 直接执行 advance | 邮件预览 fetch 触发 / 浏览器 prefetch 触发 | exchange 是 POST；GET 仅展示登录页 + 用户手动点按钮触发 POST |
| jti 黑名单 race | 双击 / 并发请求绕过一次性约束 | Redis `SET nx ex` 原子操作 |
| Mattermost callback 无签名校验 | 任何人 curl 伪造决策 | 校验 `token` 字段 或 callback URL 带 secret |
| `LANGGRAPH_STRICT_MSGPACK` 未启用 | checkpoint 被篡改可触发 RCE（反序列化任意类）| `LANGGRAPH_STRICT_MSGPACK=true`（2026 LangGraph 推荐配置） |
| 演示模式上线 | 真实用户邮件被覆写到 DEMO_INBOX | 启动 log 显式打印 mode；前端 footer 显示 mode；prod 部署 checklist |
| 错误信息泄露 token / DSN | log / API 错误响应里包含敏感数据 | error handler middleware 脱敏；不要 `repr(exception)` |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| 演示模式邮件主题没角色前缀 | 演示者收件箱分不出角色 | 必加 `[角色·username]` 前缀（PRD §7.4.1） |
| 邮件深链点了无反馈 | 用户不知道是不是登录成功 | exchange 成功立刻显示 toast "已以 li.si 身份登录" |
| 节点处理页没显示当前角色 | 演示者忘了自己在演谁 | 页面顶部 banner 显示 "当前角色：IT 设备管理员 (it.charlie)" |
| 三态按钮颜色无区分 | 容易点错"拒绝" | 继续=蓝色 / 退回=黄色 / 拒绝=红色 + confirm dialog |
| 申请人确认页时间线太长，没强调"待你确认" | 用户滑到底懵了不知道做什么 | 时间线折叠 + 主按钮在视口内固定显示 |
| 节点超时无提示 | 演示者忘了 24h 后 token 失效 | Dashboard 显示倒计时 + 一键重发邮件按钮 |
| Mattermost 推私聊 vs 公开频道 | 推到公开频道暴露所有人离职信息 | 默认推 DM；team-wide notification 仅汇总状态不含细节 |

---

## "Looks Done But Isn't" Checklist

- [ ] **LangGraph PostgresSaver:** 重启后能从 interrupt 恢复（不只是首次启动跑通）— 验证：跑到 manager_review interrupt → `docker compose restart flow-api` → 再点按钮能继续
- [ ] **节点函数双写:** 故意让 graph.invoke 失败一次 → 业务表能查到 action_log.status=failed → 有 retry 路径
- [ ] **并行节点 result_text 聚合:** 申请人最终确认邮件含全部 9 个节点的备注，每段都有 actor + 时间
- [ ] **jti 黑名单:** `pytest-asyncio.gather(exchange, exchange)` 同一 token 并发 → 必须只有一个成功
- [ ] **演示模式:** 8 个角色邮件全到达 DEMO_INBOX；主题都有角色前缀；正文有"演示模式"横幅；`notifications.recipient` 仍是真实邮箱
- [ ] **演示模式切回 prod:** `APP_MODE=prod` 后 `notifications.delivery_to == notifications.recipient`，启动 log 打印 mode
- [ ] **Seed 幂等:** `python scripts/seed_demo_data.py && python scripts/seed_demo_data.py` 两次都 0 错误
- [ ] **Mattermost 卡片按钮可点:** 不只是邮件能用，IM 里点"继续"也能推进流程（验证 `AllowedUntrustedInternalConnections` 配对）
- [ ] **Nginx 路由:** `curl /api/health` 返回 JSON，`curl /flow/xxx/node/yyy` 返回 HTML，`curl /api/不存在` 返回 JSON 404 不是 HTML
- [ ] **静态导出 build 通过:** `pnpm build` 0 error；产物可由 nginx serve；客户端路由刷新不 404
- [ ] **凭证安全:** `git log -p | grep -E "(SMTP_PASSWORD|JWT_SECRET|API_KEY)"` 0 命中
- [ ] **LLM 降级:** 故意把 GLM_API_KEY 设错 → 申请人邮件能发出（无摘要），流程能推进
- [ ] **QQ SMTP 真实可达:** 不只是单元测试 mock 通过，要真发一封到 1624456575@qq.com 收到
- [ ] **Token 一次性:** 同一邮件链接点两次 → 第二次提示"已使用，请通过 Dashboard 重发"
- [ ] **Token 过期:** 修改 `TOKEN_EXPIRY_HOURS=0.001` → 点链接报"token 已过期"，能 resend
- [ ] **Docker 内网通信:** 容器 `flow-api` 内 `curl mattermost:8065` / `curl host.docker.internal:8065` 通
- [ ] **HR Dashboard:** 显示 1 个 demo 流程，能下钻到节点详情；不显示历史脏数据
- [ ] **数据库备份:** `pg_dump` 能跑通，恢复后流程仍可继续推进

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Pitfall 2: 双写不一致（业务表 done 但 LangGraph 未推进） | MEDIUM | 跑 `scripts/recover_from_db.py`：扫 `action_logs.status='failed'`，重新 `graph.update_state + ainvoke` |
| Pitfall 3: 重复发邮件 | LOW | 给收件人发"忽略上一封重复通知"邮件；事后给节点函数加幂等检查 |
| Pitfall 5: checkpoint 序列化失败 | HIGH | 流程从头重启（newflow_id）；旧的从 DB 重建：用 `scripts/recover_from_db.py` |
| Pitfall 6: jti race（已 race 过的 token 留下问题）| LOW | Redis flushdb；让用户重新登录 |
| Pitfall 8: 凭证泄露 | HIGH | 立刻轮换所有密钥；`git filter-repo` 抹历史；强推；通知协作者 force pull |
| Pitfall 9: 数据卷被删 | HIGH | 从最近 `pg_dump` 恢复；如无备份 → 从头 seed |
| Pitfall 10: 演示模式上线 | MEDIUM | 立刻切 prod；给被覆写的真实 assignee 手工补邮件 |
| Pitfall 14: QQ SMTP 被限流 | MEDIUM | 切换 fallback MailHog；演示后等 1 小时再试 |
| Pitfall 17: thread_id 重用污染 | LOW | 删 LangGraph checkpoint + 业务表记录；新 UUID 重起 |
| Pitfall 19: Next.js build 失败 | LOW | 加 `generateStaticParams = () => []` + `dynamicParams = true` |
| Pitfall 21: 端口冲突 / Mattermost 不通 | LOW | 修 `extra_hosts`；DEEPLINK_BASE_URL 改成不带 :3000 |
| Pitfall 22: LLM 卡 | LOW | 切到 `LLM_PROVIDER=none` 让所有 LLM 调用走降级路径 |

---

## Pitfall-to-Phase Mapping

> Phase 拆分推荐（基于 PRD M1-M6 + 本研究）：
> - **P1**: Backend 骨架 + LangGraph StateGraph + PostgresSaver + Docker compose 骨架 + 业务表 schema
> - **P2**: 节点函数 + 双写规范 + 业务状态机 API + 并行扇出 / 申请人最终确认节点
> - **P3**: 鉴权 + 深链 + JWT 一次性 token + cookie + 角色视图
> - **P4**: 通知（邮件 QQ SMTP + Mattermost 双通道）+ LLM 摘要 + Seed 脚本
> - **P5**: 前端 Next.js 静态导出 + 多角色页面 + HR Dashboard
> - **P6**: nginx + docker compose 部署 + 演示模式切换 + 运维脚本 + 端到端联调

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. PostgresSaver setup | P1 | 启动 log 打印 setup 完成；重启后能恢复 state |
| 2. 双写不一致 | P2 | e2e 测试：模拟 invoke 失败 → action_log.status=failed |
| 3. interrupt 死循环 / 重复发 | P1 + P3 | 节点函数幂等检查 + API 层 idempotency_key |
| 4. 并行节点 reducer | P1 + P2 | 单测 4 并行节点 → state 含全部 decisions |
| 5. checkpoint 序列化 | P1 | `test_state_serializable.py` 跑每个节点输出 msgpack.packb 不抛异常 |
| 6. jti race | P3 | pytest-asyncio.gather 并发 exchange 测试 |
| 7. Mattermost 内网 callback | P4 | seed 启动校验 `AllowedUntrustedInternalConnections` 包含本机 |
| 8. 凭证泄露 | P1 | `.gitignore` + pre-commit gitleaks 第一个 commit 之前 |
| 9. compose down -v 误删 | P6 | dev-reset.sh 加二次确认 |
| 10. 演示模式上线 / 缺角色前缀 | P4 + P6 | EmailEnvelope 测试两种 mode；prod 部署 checklist |
| 11. Seed 不幂等 | P4 | CI 跑 seed 两次 |
| 12. Cookie Secure flag | P3 | secure=(mode==prod and HTTPS) 配置 |
| 13. URL token 泄露 | P3 + P6 | nginx log_format 不含 query；前端 router.replace |
| 14. QQ SMTP 限流 | P4 | 演示前预热；节流 + MailHog fallback |
| 15. 中文主题编码 | P4 | EmailMessage 测试断言 base64 编码正确 |
| 16. 副作用 vs 回退 | P2 | 节点函数 is_first_entry 判断 |
| 17. thread_id 重用 | P1 | 流程创建强制 uuid4()，无 query param 复用 |
| 18. Bot Token 权限 | P4 | seed 启动校验 `roles` 含 system_admin |
| 19. Next.js dynamic route build | P5 | pnpm build CI 必须通过 |
| 20. nginx 路由优先级 | P6 | 部署后 curl /api/health 返回 JSON 验证 |
| 21. 端口 / DNS | P6 | docker compose up 后 curl 容器内互通 |
| 22. LLM 阻塞 | P4 | timeout + 降级 e2e 测试（API key 故意错） |
| 23. 异步测试 fixture | P1 | conftest 用 loop_scope=session |
| 24. HTML 邮件兼容 | P4 | 4 个客户端截图测试矩阵 |
| 25. checkpoint 膨胀 | P6 | cleanup 脚本 + cron |
| 26. webhook 签名 | P4 | callback API 必须校验 token |
| 27. token 过期演示 | P5 | Dashboard resend 按钮 |
| 28. 演示前清空数据 | P6 | 演示 runbook 第一步 |

---

## 演示场景独有 vs 生产场景共有

> 这些 pitfall 标记 [DEMO-ONLY] 表示只在演示模式 / demo seed / 演示者操作场景下会出现，进入生产后会自动消失或不相关：

**[DEMO-ONLY]**: #6（双击同一邮件 — 真实用户不会双击）、#10（演示模式相关）、#11（seed 幂等 — prod 不跑 seed）、#14（QQ SMTP — prod 用企业 SMTP）、#27（token 过期间隔 — prod 用户操作密集）、#28（清空数据 — prod 不清）

**[PROD-ONLY 关键]**: 演示阶段可松，prod 必须严：#12（Secure cookie，prod 必须 HTTPS）、#25（checkpoint GC）、#26（webhook 签名校验）

**两者都关键**：#1-#5（LangGraph 核心机制）、#7-#9（基础设施）、#13（log 安全）、#15-#23（实现质量）

---

## Sources

- [LangGraph PostgresSaver 官方文档（langgraph-checkpoint-postgres PyPI）](https://pypi.org/project/langgraph-checkpoint-postgres/) — HIGH，确认 setup() + autocommit + dict_row 要求
- [LangGraph Persistence Guide 2026](https://fast.io/resources/langgraph-persistence/) — HIGH，确认 state 大对象避免 / LANGGRAPH_STRICT_MSGPACK
- [LangGraph issue #7780 Interrupt in loop causes extra resumes](https://github.com/langchain-ai/langgraph/issues/7780) — HIGH，证实 interrupt 循环 race
- [LangGraph issue #1138 checkpoint 表无界增长](https://github.com/langchain-ai/langgraphjs/issues/1138) — HIGH，证实 GC 必要
- [LangGraph Interrupts Docs](https://docs.langchain.com/oss/python/langgraph/interrupts) — HIGH
- [LangGraph Best Practices (swarnendu.de)](https://www.swarnendu.de/blog/langgraph-best-practices/) — MEDIUM
- [Mattermost AllowedUntrustedInternalConnections 官方文档](https://docs.mattermost.com/administration-guide/configure/environment-configuration-settings.html) — HIGH
- [Mattermost forum: Outgoing webhook failing on internal site](https://forum.mattermost.com/t/solved-outgoing-webhook-failing-silently-on-internal-site-even-after-allowing-untrusted-internal-connections/19250) — HIGH，证实 `err=address forbidden` 现象
- [Mattermost interactive messages plugin docs](https://developers.mattermost.com/integrate/plugins/interactive-messages/) — HIGH
- [Mattermost issue #9241 plugins 默认 internal connections](https://github.com/mattermost/mattermost/issues/9241) — MEDIUM
- [Next.js generateStaticParams 官方文档](https://nextjs.org/docs/app/api-reference/functions/generate-static-params) — HIGH
- [Next.js static exports guide](https://nextjs.org/docs/app/guides/static-exports) — HIGH，确认 dynamicParams 用法
- [Next.js issue #56253 output:export + generateStaticParams + dynamic](https://github.com/vercel/next.js/issues/56253) — HIGH，证实组合 bug
- [Next.js discussion #64660 useParams in export mode](https://github.com/vercel/next.js/discussions/64660) — HIGH
- [QQ SMTP Field Manual](https://smtpfieldmanual.com/provider/qq/) — HIGH，证实 550 频率限制
- [QQ Mail 550 Ip frequency limited 排查](https://www.computersolutions.cn/blog/qq-mail-550-ip-frequency-limited-errors-and-how-to-solve-them/) — MEDIUM
- [OWASP HttpOnly](https://owasp.org/www-community/HttpOnly) — HIGH
- [MDN HTTP Cookies — Secure attribute](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Cookies) — HIGH，证实 Secure on HTTP 行为
- 本项目 PRD v0.3 / PROJECT.md — HIGH（架构和演示模式细节来源）
- 个人经验：FastAPI + asyncio + pytest-asyncio fixture scope 已知坑（Pitfall 23）— MEDIUM

---
*Pitfalls research for: LangGraph + FastAPI + Next.js 离职流程系统（面试演示项目，1-2 周端到端 demo）*
*Researched: 2026-05-16*
