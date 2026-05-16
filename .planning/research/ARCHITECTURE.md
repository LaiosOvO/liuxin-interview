# Architecture Research — LangGraph + FastAPI + Next.js 状态机驱动的离职流程系统

**Domain:** 状态机驱动的人工审批工作流引擎（HR offboarding）
**Researched:** 2026-05-16
**Confidence:** HIGH（LangGraph / FastAPI / Postgres / JWT 主线均为 2026 主流文档背书；Next.js static-export 动态路由部分 MEDIUM）

---

## 0. 摘要：一句话架构

> **一个 FastAPI 进程托管 LangGraph 引擎，业务表与 PostgresSaver checkpoint 共库不同 schema 双写；人工节点通过 `interrupt()` 挂起，邮件深链携带一次性 JWT 唤醒，Cookie 鉴权后 `Command(resume=...)` 推进；Next.js 静态导出 + nginx 反代提供前端；APScheduler 同进程跑超时扫描，通知发送走轻量 outbox。**

所有"双层状态、人工中断恢复、并行扇出、双通道通知"在这套架构里全部是 **single-process monolith + 单一 Postgres + 单一 Redis** 就能跑完，零分布式队列，零 worker 进程。是面试演示项目的合理 sizing；如果上量再切 Celery。

---

## 1. Standard Architecture

### 1.1 System Overview

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                      浏览器（多角色：employee/manager/hr/it/finance/legal）   │
└────────────────────────┬────────────────────────────┬────────────────────────┘
                         │  HTTP                       │  Cookie (HttpOnly)
                         ▼                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        nginx (192.168.2.44:80)                                │
│  location /            → /usr/share/nginx/html (Next.js static export)        │
│  location /api/        → http://flow-api:8000                                 │
│  location /ws/         → http://flow-api:8000 (Upgrade)                       │
└─────────┬─────────────────────────────────────────────┬──────────────────────┘
          │ 静态文件                                     │ 反代
          ▼                                              ▼
┌─────────────────────────┐    ┌─────────────────────────────────────────────────┐
│   Next.js 静态产物 out/ │    │              FastAPI (uvicorn, 1 进程)          │
│   - 壳页面 + JS chunks  │    │  ┌─────────────────────────────────────────┐    │
│   - useParams 客户端取  │    │  │  routers/        (HTTP 入口)            │    │
│     flow_id/node_id     │    │  │    auth/exchange  flows/  nodes/        │    │
└─────────────────────────┘    │  │    notifications/                       │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  services/      (业务编排)              │    │
                                │  │    flow_service  node_service  auth_svc │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  flow_engine/   (LangGraph 单例)        │    │
                                │  │    graph_builder (DAG 装配)             │    │
                                │  │    nodes/*.py    (10 个节点函数)        │    │
                                │  │    state.py      (TypedDict + reducer)  │    │
                                │  │  ├─ AsyncPostgresSaver (langgraph 表)   │    │
                                │  │  └─ interrupt() / Command(resume=...)   │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  state_store/   (业务表 Repository)     │    │
                                │  │    flow_repo  node_repo  log_repo       │    │
                                │  │    outbox_repo                          │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  notifications/  (双通道 dispatcher)    │    │
                                │  │    email_sender  mattermost_sender      │    │
                                │  │    outbox_worker (后台 loop)            │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  auth/           (JWT + jti 黑名单)     │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  llm/            (GLM client, 摘要)     │    │
                                │  ├─────────────────────────────────────────┤    │
                                │  │  scheduler/      (APScheduler in-proc)  │    │
                                │  │    timeout_scan  outbox_drain           │    │
                                │  └─────────────────────────────────────────┘    │
                                └────┬─────────────────┬──────────────────────────┘
                                     │                 │
                  ┌──────────────────▼──┐         ┌────▼────────────────────┐
                  │  PostgreSQL         │         │  Redis                  │
                  │  ┌───────────────┐  │         │  ┌─────────────────┐    │
                  │  │ schema: app   │  │         │  │ jti:blacklist:* │    │
                  │  │  flow_instances│ │         │  │   (SET + TTL)   │    │
                  │  │  node_states  │  │         │  │ outbox:queue    │    │
                  │  │  action_logs  │  │         │  │ apscheduler:*   │    │
                  │  │  notifications│  │         │  └─────────────────┘    │
                  │  │  notification_outbox │    │  (可选，PG 也能扛)        │
                  │  │  users        │  │         └─────────────────────────┘
                  │  └───────────────┘  │
                  │  ┌───────────────┐  │         ┌──────────────────────┐
                  │  │ schema:langgraph│         │  外部服务             │
                  │  │  checkpoints  │  │         │  - SMTP smtp.qq.com  │
                  │  │  checkpoint_writes│       │  - Mattermost 8065   │
                  │  │  checkpoint_blobs│        │  - GLM API           │
                  │  └───────────────┘  │         └──────────────────────┘
                  └─────────────────────┘
```

### 1.2 Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **nginx** | TLS 终结（v1 跳过）、静态文件 serve、反代 `/api/` 与 `/ws/`、`try_files /index.html` 兜底前端路由 | docker `nginx:alpine` + 自定义 `nginx.conf` |
| **Next.js 静态产物** | 多角色 dashboard、节点处理页、状态时间线；`useParams()` 读 URL 路径，`fetch` 调 FastAPI | `output: 'export'` + `pnpm build` → `out/` 拷进 nginx 镜像 |
| **FastAPI routers** | HTTP 入口、请求校验、依赖注入、错误统一信封 | `APIRouter` + `Depends` + Pydantic v2 |
| **flow_service / node_service** | 业务编排：调 state_store 写业务表 → 调 flow_engine 更新 LangGraph → 触发通知 | 纯 async Python 类，单一职责 |
| **flow_engine (LangGraph)** | DAG 编排、checkpoint 持久化、`interrupt()` 挂起、`Command(resume=...)` 恢复、并行 fan-out/fan-in | `StateGraph` + `AsyncPostgresSaver`，全局单例 |
| **节点函数 nodes/*.py** | 每个节点的"进入副作用"：写 node_states + 推 notification_outbox + 调 interrupt() | 每个节点一个 `.py` 文件（high cohesion, low coupling） |
| **state_store (Repository)** | 业务表唯一访问路径，封装事务边界 | SQLAlchemy 2.x async + asyncpg + repository 模式 |
| **notifications/** | 渲染模板、写 outbox、后台 worker drain outbox、调用 SMTP/Mattermost | aiosmtplib + httpx，模板用 Jinja2 |
| **auth/** | JWT 签发/校验、jti 一次性消费、Cookie 签发、role 校验 dep | `PyJWT` + Redis SET（jti 黑名单） |
| **scheduler/** | 超时扫描（每分钟扫 `waiting_human` 节点）、outbox drain（每 10s 拉未发通知） | `APScheduler AsyncIOScheduler`，进程内 |
| **llm/** | GLM API 客户端、最终确认节点的摘要生成 | httpx + retry + 失败降级（不阻塞节点）|
| **postgres** | 业务表 + LangGraph checkpoint 同实例不同 schema | Postgres 16，`search_path` 隔离 |
| **redis** | jti 黑名单（带 TTL = token 剩余有效期） + APScheduler jobstore（可选） | Redis 7 |

---

## 2. Recommended Project Structure

```
hr/
├── backend/
│   ├── pyproject.toml          # uv 管理
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/           # 仅业务表 migration，langgraph schema 由 saver.setup() 管
│   ├── scripts/
│   │   ├── entrypoint.sh       # alembic upgrade head → langgraph setup → uvicorn
│   │   ├── seed_demo_data.py   # 8 个测试账号 + 5 个 team
│   │   └── recover_from_db.py  # 崩溃恢复工具（业务表 → LangGraph state 重建）
│   ├── app/
│   │   ├── main.py             # FastAPI app, lifespan 启动 graph/scheduler
│   │   ├── settings.py         # Pydantic Settings, 读 .env
│   │   ├── deps.py             # DI（db session, current_user, role 校验）
│   │   ├── routers/
│   │   │   ├── auth.py         # POST /api/auth/exchange
│   │   │   ├── flows.py        # POST /api/flows, GET /api/flows/{id}, /my/flows
│   │   │   ├── nodes.py        # GET .../nodes/{id}/view, POST .../actions
│   │   │   ├── notifications.py# POST /api/notifications/{id}/resend
│   │   │   └── health.py
│   │   ├── services/
│   │   │   ├── flow_service.py # 起流程 / 查流程 / 终止流程
│   │   │   ├── node_service.py # 提交三态决策 → 写表 → 唤醒 LangGraph
│   │   │   └── auth_service.py # token 签发 / 交换 / jti 黑名单
│   │   ├── flow_engine/
│   │   │   ├── state.py        # OffboardingState TypedDict + reducer 标注
│   │   │   ├── graph.py        # build_graph() 工厂函数, get_graph() 单例
│   │   │   ├── checkpointer.py # AsyncPostgresSaver init（schema=langgraph）
│   │   │   ├── templates/
│   │   │   │   └── standard_offboarding.py  # DAG + 退回路由表
│   │   │   ├── nodes/
│   │   │   │   ├── apply.py
│   │   │   │   ├── manager_review.py
│   │   │   │   ├── hr_initial.py
│   │   │   │   ├── parallel_fanout.py       # 触发 4 路并行的 dispatcher
│   │   │   │   ├── device_return.py
│   │   │   │   ├── access_revoke.py
│   │   │   │   ├── knowledge_handover.py
│   │   │   │   ├── finance_settle.py
│   │   │   │   ├── legal_sign.py
│   │   │   │   ├── hr_final.py
│   │   │   │   ├── applicant_final_confirm.py
│   │   │   │   └── archive.py
│   │   │   └── routing.py      # route_after_xxx 条件边函数
│   │   ├── state_store/
│   │   │   ├── models.py       # SQLAlchemy ORM (业务表)
│   │   │   ├── flow_repo.py
│   │   │   ├── node_repo.py
│   │   │   ├── log_repo.py
│   │   │   ├── outbox_repo.py
│   │   │   └── session.py      # async_session_maker
│   │   ├── notifications/
│   │   │   ├── dispatcher.py   # 写 outbox（事务内）
│   │   │   ├── outbox_worker.py# 后台 loop：拉 outbox → 发送 → 标记
│   │   │   ├── email_sender.py # aiosmtplib + 演示模式覆写
│   │   │   ├── mattermost_sender.py
│   │   │   ├── templates/      # Jinja2: final_confirm.html, generic.html
│   │   │   └── deeplink.py     # build_deep_link(flow_id, node_id, sub)
│   │   ├── auth/
│   │   │   ├── jwt.py          # encode/decode, sign(jti, payload)
│   │   │   ├── blacklist.py    # Redis set/check (TTL = exp - now)
│   │   │   └── cookie.py       # 签发 HttpOnly Cookie
│   │   ├── llm/
│   │   │   ├── glm_client.py
│   │   │   └── summarize.py    # summarize_node_results(results) → str | None
│   │   └── scheduler/
│   │       ├── lifespan.py     # 在 FastAPI lifespan 中启停
│   │       ├── timeout_scan.py # 每分钟扫 waiting_human > 24h
│   │       └── outbox_drain.py # 每 10s 触发 outbox_worker
│   └── tests/
│       ├── unit/               # repository, jwt, dispatcher (mock SMTP)
│       ├── integration/        # 端到端节点函数 + 真实 PG
│       └── e2e/                # API → graph → DB 全链路
│
├── frontend/
│   ├── package.json            # pnpm
│   ├── next.config.ts          # output: 'export', images.unoptimized: true
│   ├── tailwind.config.ts
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx            # 落地页 / 角色入口
│   │   ├── flow/
│   │   │   └── [flow_id]/
│   │   │       └── node/
│   │   │           └── [node_id]/
│   │   │               └── page.tsx   # 'use client' + useParams + token 交换
│   │   ├── my/
│   │   │   └── flows/page.tsx
│   │   └── hr/
│   │       └── dashboard/page.tsx
│   ├── components/
│   │   ├── NodeForm.tsx        # 通用三态表单
│   │   ├── ApplicantConfirm.tsx# 含时间线 + GLM 摘要
│   │   └── ui/                 # shadcn/ui 生成
│   └── lib/
│       ├── api.ts              # fetch wrapper, /api/* 前缀
│       └── auth.ts             # exchange token, role 路由
│
├── deploy/
│   ├── docker-compose.yml
│   ├── nginx/
│   │   └── nginx.conf
│   └── .env.example
└── docs/
    └── reading-*.md            # 参考项目阅读笔记
```

### Structure Rationale

- **`backend/app/flow_engine/`：** LangGraph 相关代码全部聚合，业务侧（routers/services）只通过 `get_graph()` 拿单例，避免引擎细节外泄。每个节点一个文件 = 200 行以内 = 符合"many small files"原则。
- **`backend/app/state_store/`：** Repository 模式封装所有业务表 SQL；节点函数注入 repo，不直接写 ORM。**任何业务查询都不读 langgraph schema**（架构强约束的代码化体现）。
- **`backend/app/notifications/`：** dispatcher 只负责"写 outbox"，发送由 `outbox_worker` 异步 drain。HTTP 路径上**不阻塞**等 SMTP（QQ SMTP 偶发 5-10s 延迟很正常）。
- **`backend/app/auth/`：** jwt + blacklist + cookie 三件套独立，方便单测；jti 黑名单走 Redis（TTL 自动清理），失败降级到 PG `consumed_tokens` 表（v1 可只用 Redis）。
- **`backend/app/scheduler/`：** APScheduler 在 FastAPI lifespan 启停；超时扫描和 outbox drain 是两个独立 job。
- **`frontend/app/flow/[flow_id]/node/[node_id]/page.tsx`：** Next.js 15 静态导出 + 动态路由的**唯一可行方式**——加 `'use client'`，用 `useParams()` 读运行时参数，避开 `generateStaticParams` 限制（v1 单一动态路径，绕过 issue #79380）。

---

## 3. Architectural Patterns

### Pattern 1: 双层状态 + 节点函数双写（核心模式）

**What:** LangGraph runtime checkpoint（引擎私有）与业务表（UI/审计/报表）是两份独立持久化；节点函数在同一事务内写业务表 + 推送通知（outbox），然后才返回 state；FastAPI 路由提交决策时反向更新 LangGraph state 后 `ainvoke(None)` 恢复。

**When to use:** 任何"引擎私有 state ≠ 业务可读 state"的工作流场景；本项目刚需。

**Trade-offs:**
- ✅ HR Dashboard 多维查询走业务表（SQL JOIN/索引），与 LangGraph 版本升级解耦
- ✅ 崩溃后以业务表为权威重建（PRD §5.3.2）
- ⚠ 双写一致性需要约定：**业务表写成功 + outbox 写成功 → 才能调 `graph.aupdate_state` + `graph.ainvoke`**；任何一步失败回滚事务，LangGraph 侧不动
- ⚠ 调试时要看两个地方

**Example:**

```python
# nodes/manager_review.py
async def manager_review_node(state: OffboardingState) -> dict:
    flow_id = state["flow_id"]
    async with async_session_maker() as session:
        async with session.begin():
            # 1. 业务表：upsert node_states
            node_state = await node_repo.upsert(
                session, flow_id=flow_id, node_name="manager_review",
                status="waiting_human",
                assignee=await lookup_manager(session, state["employee_id"]),
                entered_at=now(),
            )
            # 2. 通知 outbox（同事务）
            await outbox_repo.enqueue_email(
                session, node_state_id=node_state.id,
                recipient=node_state.assignee_email,
                template="generic_node", context={...},
            )
            await outbox_repo.enqueue_mattermost(session, ...)
    # 3. 触发 interrupt（事务已 commit）
    decision = interrupt({
        "node_id": str(node_state.id),
        "prompt": "等待上级审批",
    })
    # 4. 恢复后 decision 是 FastAPI 路由通过 Command(resume=decision) 传入的字典
    return {
        "decisions": {"manager_review": decision},
        "current_action": decision["action"],
    }
```

```python
# services/node_service.py
async def submit_action(flow_id, node_id, action, result_text, reason, actor):
    async with async_session_maker() as session:
        async with session.begin():
            # 1. 写 action_logs + 更新 node_states + append node_results
            await log_repo.write(session, flow_id, node_id, action, result_text, reason, actor)
            await node_repo.complete(session, node_id, result_text=result_text)
            await flow_repo.append_node_result(session, flow_id, {...})
            # 2. 失效该 node 的所有未消费 token
            await auth_service.invalidate_tokens_for_node(session, node_id)
    # 3. 事务 commit 后才唤醒 LangGraph
    graph = get_graph()
    await graph.ainvoke(
        Command(resume={"action": action, "result_text": result_text, "reason": reason}),
        config={"configurable": {"thread_id": str(flow_id)}},
    )
```

### Pattern 2: Dynamic interrupt（推荐）vs Static interrupt_before

**What:** 用 LangGraph 的**动态 `interrupt()`** 函数（节点内调用）而不是编译期 `interrupt_before=[...]`。

**When to use:** 本项目所有人工节点。

**Trade-offs:**
- ✅ 动态 interrupt 在事务 commit **之后**调用，保证"业务表 + outbox 都落地"才挂起
- ✅ 可向 interrupt 传 payload（如 prompt/options），前端可拿到结构化提示
- ✅ Resume 用 `Command(resume=value)` 把决策直接传回节点，无需额外 `update_state`
- ✅ 是 LangChain 2026 推荐做法（HITL middleware 已转向 dynamic）
- ⚠ Static `interrupt_before` 在节点函数**进入之前**就挂起 → 节点的"进入副作用"（写表 + 发通知）必须在**上游节点**完成，违反职责分离
- ⚠ 团队需要理解：interrupt() 抛 GraphInterrupt 异常，节点函数会被重试执行（保证写入路径幂等！）

**Example:**

```python
from langgraph.types import interrupt, Command

async def hr_initial_node(state: OffboardingState) -> dict:
    # 进入副作用 (幂等)
    await _ensure_node_state_entered(state["flow_id"], "hr_initial")
    # 挂起，等待 Command(resume=...)
    decision = interrupt({
        "node_id": ..., "actions": ["advance", "return", "reject"],
    })
    # 恢复后到这里
    return {"decisions": {"hr_initial": decision}, "current_action": decision["action"]}
```

**关键 gotcha：** interrupt 抛 GraphInterrupt 后整个节点函数会在 resume 时**从头重跑**。所有副作用必须幂等（用 `upsert` 而非 `insert`，outbox 写入用 `(flow_id, node_id, channel)` 唯一约束）。

### Pattern 3: 业务表 + LangGraph schema 同实例隔离

**What:** Postgres 单实例、单 database、两个 schema（`app` + `langgraph`），通过 SQLAlchemy `search_path` 和 AsyncPostgresSaver 的 `schema_name` 参数隔离。

**When to use:** 单机部署 + 想要事务边界一致 + 不想运维两个 DB。

**Trade-offs:**
- ✅ 一个 Postgres 容器，备份/迁移简单
- ✅ 跨 schema **不共享事务**（业务表写入与 checkpoint 写入是独立事务，符合双层状态设计）
- ✅ 权限可分（`GRANT USAGE ON SCHEMA langgraph TO flow_user` 但禁止业务代码 `SELECT * FROM langgraph.checkpoints`）
- ⚠ AsyncPostgresSaver 的 `setup()` 必须在 alembic migration **之外**单独跑一次（PRD §10.2 启动顺序），避免重复建表

**Example:**

```python
# flow_engine/checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

async def init_checkpointer(dsn: str) -> AsyncPostgresSaver:
    pool = AsyncConnectionPool(conninfo=dsn, max_size=10, open=False)
    await pool.open()
    saver = AsyncPostgresSaver(pool)
    # 仅首次启动时建表；幂等
    await saver.setup()  # 在 langgraph schema 下建 checkpoints/checkpoint_writes/checkpoint_blobs
    return saver

# alembic env.py
def include_object(object, name, type_, reflected, compare_to):
    # alembic 只管 app schema
    if type_ == "table" and object.schema == "langgraph":
        return False
    return True
```

```sql
-- 初始化 SQL（entrypoint.sh 启动前执行一次）
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION flow;
CREATE SCHEMA IF NOT EXISTS langgraph AUTHORIZATION flow;
ALTER ROLE flow SET search_path TO app, public;
```

### Pattern 4: Parallel fan-out + Annotated reducer

**What:** TypedDict 中并行节点写入的字段必须用 `Annotated[list, operator.add]` 标注 reducer，否则后写者覆盖前写者。

**When to use:** PRD §4.1 的设备归还/权限回收/知识交接/财务结算/法务签字 5 路并行。

**Trade-offs:**
- ✅ LangGraph 原生支持，零额外代码
- ⚠ 最常见 bug 就是漏 reducer，列表只保留最后一路；TypedDict 写 `list[X]` 而非 `Annotated[list[X], operator.add]` 会静默丢数据

**Example:**

```python
# flow_engine/state.py
from typing import TypedDict, Annotated
from operator import add

class NodeResult(TypedDict):
    node_name: str
    actor: str
    result_text: str
    completed_at: str

class OffboardingState(TypedDict):
    flow_id: str
    employee_id: str
    current_action: str
    decisions: dict
    # 并行节点都往这里追加 → 必须 reducer
    parallel_results: Annotated[list[NodeResult], add]
    # 全局聚合（节点函数内严格"复制 + 追加"，否则会被默认 last-write-wins 覆盖）
    node_results: Annotated[list[NodeResult], add]
```

```python
# graph.py
graph.add_edge("hr_initial", "device_return")
graph.add_edge("hr_initial", "access_revoke")
graph.add_edge("hr_initial", "knowledge_handover")
graph.add_edge("hr_initial", "finance_settle")
# fan-in：5 路都完成才进 legal_sign
graph.add_edge(["device_return", "access_revoke", "knowledge_handover", "finance_settle"], "legal_sign")
```

### Pattern 5: 通知 = 轻量 outbox（事务内入队 + 后台 drain）

**What:** 节点函数在业务事务里 `INSERT INTO notification_outbox`；后台 `outbox_worker` 每 10s 轮询 status=pending → 调 SMTP/Mattermost → UPDATE status=sent/failed。

**When to use:** 本项目就用它。**不要**在节点函数内直接 `await smtp.send()` —— QQ SMTP 偶尔 5-10s 卡顿会卡死 graph 推进。

**Trade-offs:**
- ✅ 节点函数在 sub-100ms 内完成 → graph 推进顺畅
- ✅ 通知发送失败可重试（status=failed + attempts，重试上限后告警）
- ✅ 与业务事务原子（事务回滚则不会有 ghost 通知）
- ⚠ 多进程部署需要 `SELECT FOR UPDATE SKIP LOCKED` 防并发重发；v1 单进程不需要
- ⚠ 比"直接发 + try/except"重一些；但比上 Celery 轻得多

**Example:**

```sql
CREATE TABLE app.notification_outbox (
  id UUID PRIMARY KEY,
  flow_id UUID NOT NULL,
  node_state_id UUID NOT NULL,
  channel VARCHAR(16) NOT NULL,    -- email | mattermost
  recipient VARCHAR(256) NOT NULL,
  payload JSONB NOT NULL,          -- 渲染好的主题/正文/按钮
  status VARCHAR(16) DEFAULT 'pending',  -- pending | sent | failed
  attempts INT DEFAULT 0,
  last_error TEXT,
  next_retry_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT now(),
  sent_at TIMESTAMP,
  UNIQUE(flow_id, node_state_id, channel)   -- 幂等保护
);
CREATE INDEX ON app.notification_outbox (status, next_retry_at) WHERE status IN ('pending', 'failed');
```

```python
# notifications/outbox_worker.py
async def drain_once(batch_size: int = 20):
    async with async_session_maker() as session:
        async with session.begin():
            rows = await outbox_repo.lease_pending(session, limit=batch_size)  # SELECT ... FOR UPDATE SKIP LOCKED
            for row in rows:
                try:
                    if row.channel == "email":
                        await email_sender.send(row)
                    elif row.channel == "mattermost":
                        await mattermost_sender.send(row)
                    await outbox_repo.mark_sent(session, row.id)
                except Exception as e:
                    await outbox_repo.mark_failed(session, row.id, str(e),
                        next_retry_at=now() + backoff(row.attempts))
```

### Pattern 6: JWT 一键登录 + 一次性 jti

**What:** 邮件深链携带 JWT；前端 POST `/api/auth/exchange` → 校验签名/过期/jti 未消费/sub 匹配 assignee → 写 jti 到 Redis（TTL=exp-now） → 签发 HttpOnly Cookie。

**When to use:** PRD §6.2 已锁定。

**Trade-offs:**
- ✅ Redis SETNX + TTL 自动清理，操作 < 1ms
- ✅ 节点状态变更时主动失效该 node 所有未消费 token（清掉对应 jti 集合）
- ⚠ 内网无 TLS → token 在链路上是明文；演示 OK，生产必须 HTTPS（PRD 已声明）
- ⚠ Redis 单点故障 → 降级到 PG `consumed_tokens` 表（带索引 `(jti)` + `(exp)` 定期清理）

**Example:**

```python
# auth/blacklist.py
async def consume_jti(redis, jti: str, exp_ts: int) -> bool:
    """SET NX EX — 返回 True 表示首次消费，False 表示已使用过"""
    ttl = max(exp_ts - int(time.time()), 1)
    return await redis.set(f"jti:consumed:{jti}", "1", nx=True, ex=ttl)

async def invalidate_node_tokens(redis, node_id: str):
    """节点状态变更时清掉该 node 所有 jti（用 SET 维护 node→jti 映射）"""
    members = await redis.smembers(f"node:jti:{node_id}")
    if members:
        pipe = redis.pipeline()
        for jti in members:
            pipe.set(f"jti:consumed:{jti}", "1", ex=86400)
        await pipe.delete(f"node:jti:{node_id}")
        await pipe.execute()
```

### Pattern 7: APScheduler in-process（超时扫描 + outbox drain）

**What:** `AsyncIOScheduler` 在 FastAPI lifespan 内启动；两个 job：

- `outbox_drain`：每 10s 触发 `drain_once()`
- `timeout_scan`：每 60s 扫 `node_states.status='waiting_human' AND entered_at < now() - interval '24h'` → 给 outbox 再 enqueue 一条 reminder

**When to use:** 单进程部署 + 任务非关键。

**Trade-offs:**
- ✅ 零额外进程，零额外配置
- ✅ 与 FastAPI 共享事件循环和 DB pool
- ⚠ 多进程部署需要 jobstore（如 Redis/PG）+ leader 选举；v1 单进程 `MemoryJobStore` 足够
- ⚠ 进程重启 → 内存 job 丢失（但 outbox 表是 source of truth，重启后会重新 drain；无问题）

**Example:**

```python
# scheduler/lifespan.py
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    await init_checkpointer(settings.POSTGRES_DSN)
    scheduler = AsyncIOScheduler()
    scheduler.add_job(drain_once, "interval", seconds=10, id="outbox_drain")
    scheduler.add_job(scan_timeouts, "interval", seconds=60, id="timeout_scan")
    scheduler.start()
    app.state.scheduler = scheduler
    yield
    # shutdown
    scheduler.shutdown(wait=True)
```

### Pattern 8: Next.js 静态导出 + 客户端动态路由

**What:** 一个 `app/flow/[flow_id]/node/[node_id]/page.tsx`，加 `'use client'`，用 `useParams()` 读 ID。**不写** `generateStaticParams`（流程实例是运行时数据，无法预生成）。

**When to use:** PRD §10.0.1 已锁定，唯一活路。

**Trade-offs:**
- ✅ nginx 直接 serve，无 Node 运行时
- ⚠ Next.js 15 对"纯 CSR + 动态路由 + output: export"支持有缺陷（issue #79380），workaround：
  - **方案 A（推荐）：** 写 `generateStaticParams` 返回 `[]`，让 build 通过；nginx `try_files $uri $uri.html /index.html` 把所有未命中路径兜底到 index.html，前端 router 读 URL
  - **方案 B：** 把动态路由改成 query string（`/flow?flow_id=xxx&node_id=yyy`），完全规避问题
- ⚠ SEO 不存在（内网工具，无所谓）

**Example:**

```tsx
// app/flow/[flow_id]/node/[node_id]/page.tsx
'use client';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

export function generateStaticParams() {
  return []; // 空 stub，让 build 过
}

export const dynamic = 'force-static';
export const dynamicParams = true;

export default function NodePage() {
  const params = useParams<{ flow_id: string; node_id: string }>();
  const search = useSearchParams();
  const router = useRouter();
  const [view, setView] = useState(null);

  useEffect(() => {
    const token = search.get('token');
    if (token) {
      fetch('/api/auth/exchange', { method: 'POST', body: JSON.stringify({ token }), credentials: 'include' })
        .then(r => r.json())
        .then(data => {
          router.replace(`/flow/${params.flow_id}/node/${params.node_id}`);
          return fetch(`/api/flows/${params.flow_id}/nodes/${params.node_id}/view`, { credentials: 'include' });
        })
        .then(r => r.json())
        .then(setView);
    } else {
      fetch(`/api/flows/${params.flow_id}/nodes/${params.node_id}/view`, { credentials: 'include' })
        .then(r => r.json()).then(setView);
    }
  }, [params, search, router]);

  if (!view) return <Loading />;
  return <NodeForm view={view} onSubmit={...} />;
}
```

---

## 4. Data Flow

### 4.1 流程发起 → 第一封邮件送达

```
[zhang.san 浏览器] POST /api/flows  {employee_id: EMP001, template: standard_offboarding}
   ↓
[FastAPI flows.py] flow_service.create_flow()
   ↓
[flow_service]
   ├── 事务 begin
   ├── flow_repo.insert(flow_instances, status=running)
   ├── 事务 commit
   ↓
[flow_service] graph.ainvoke(initial_state, config={"thread_id": flow_id})
   ↓
[LangGraph]
   ├── apply_node (auto-advance)
   ├── manager_review_node 进入：
   │   ├── 事务 begin
   │   ├── node_repo.upsert(status=waiting_human, assignee=li.si)
   │   ├── outbox_repo.enqueue(email, mattermost)
   │   ├── 事务 commit
   │   └── interrupt({...})  → GraphInterrupt
   ↓
[FastAPI] HTTP 返回 {flow_id, status: "waiting", current_node: "manager_review"}
   ↓ (异步、不阻塞 HTTP 响应)
[APScheduler outbox_drain，10s 后]
   ├── outbox_repo.lease_pending() → 取 2 条
   ├── email_sender.send() → smtp.qq.com:465 → li.si 邮箱
   └── mattermost_sender.send() → POST mattermost/api/v4/posts → @li.si
   ↓
[li.si 邮箱] 收到邮件「[上级·li.si] 离职流程 — 张三 — 上级审批待处理」+ 立即处理按钮
```

### 4.2 用户点击邮件 → 决策提交 → 流程恢复

```
[li.si 点击邮件按钮]
   ↓ GET http://192.168.2.44/flow/{flow_id}/node/{node_id}?token=eyJ...
[nginx] try_files → /index.html
   ↓
[Next.js client]
   ├── useParams() → {flow_id, node_id}
   ├── useSearchParams() → token
   ├── POST /api/auth/exchange {token}
   ↓
[FastAPI auth_service.exchange_token()]
   ├── jwt.decode(token) → payload {sub, role, flow_id, node_id, jti, exp}
   ├── 校验 (flow_id, node_id, sub) 与 payload 一致
   ├── 校验 node_states.assignee == sub 且 status == waiting_human
   ├── blacklist.consume_jti(jti, exp) → True（首次）
   ├── cookie.issue_session_cookie(sub, role, flow_id) → Set-Cookie HttpOnly
   ↓
[Next.js] redirect /flow/{flow_id}/node/{node_id} （去掉 token）
   ├── fetch /api/flows/{flow_id}/nodes/{node_id}/view → 拿节点详情
   └── 渲染 NodeForm（说明 / 文本框 / 三按钮）
   ↓
[li.si 输入文本 + 点「继续」]
   ↓ POST /api/flows/{flow_id}/nodes/{node_id}/actions
         body: {action: advance, result_text: "同意，已沟通..."}
         cookie: session
   ↓
[FastAPI nodes.py] node_service.submit_action()
   ├── 事务 begin
   ├── log_repo.write(action_logs, action=advance, actor=li.si)
   ├── node_repo.complete(node_id, result_text, completed_at)
   ├── flow_repo.append_node_result(flow_id, {...})
   ├── auth_service.invalidate_tokens_for_node(node_id)
   ├── 事务 commit
   ├── graph.ainvoke(Command(resume={action, result_text}),
   │                 config={"thread_id": flow_id})
   ↓
[LangGraph]
   ├── manager_review_node 从 interrupt() 恢复 → return decision
   ├── route_after_manager_review(state) → "hr_initial"
   ├── hr_initial_node 进入 → 双写 + interrupt()
   ↓
[FastAPI] HTTP 返回 {next_node: "hr_initial", current_assignee: "hr.alice"}
   ↓
[10s 内 APScheduler 触发 outbox_drain]
   └── hr.alice 收到下一封邮件
```

### 4.3 并行扇出 → 并行决策 → 扇入

```
[hr_initial advance]
   ↓
[parallel_fanout_node]
   ├── 同事务双写 4 个 node_states (waiting_human) + 4 条 outbox
   └── 4 路并行启动
   ↓
   ├── device_return    → it.charlie    （interrupt 等待）
   ├── access_revoke    → it.charlie    （interrupt 等待）
   ├── knowledge_handover → li.si       （interrupt 等待）
   └── finance_settle   → fin.david     （interrupt 等待）
   ↓ （任意顺序到达）
   ├── it.charlie 完成 device_return  → resume → parallel_results.append({...})
   ├── it.charlie 完成 access_revoke  → resume → parallel_results.append({...})
   ├── li.si 完成 knowledge_handover  → resume → parallel_results.append({...})
   └── fin.david 完成 finance_settle  → resume → parallel_results.append({...})
   ↓ （4 路都到达才触发）
[fan-in → legal_sign]
   └── legal.eve 收到邮件
```

### 4.4 申请人最终确认（LLM 介入）

```
[hr_final advance]
   ↓
[applicant_final_confirm_node]
   ├── 从 flow_instances.context.node_results[] 聚合所有节点结果
   ├── try: summary = await glm.summarize(node_results)   # 失败降级 → summary=None
   ├── 事务 begin
   ├── outbox_repo.enqueue_email(
   │     recipient=zhang.san 邮箱（演示模式→DEMO_INBOX）,
   │     template="final_confirm.html",
   │     context={node_results, summary, deep_link})
   ├── node_repo.upsert(status=waiting_human, assignee=zhang.san)
   ├── 事务 commit
   └── interrupt(...)
   ↓
[zhang.san 收到「[申请人·zhang.san] 你的离职流程已完成审核，请最终确认」]
   ├── 邮件正文：GLM 摘要段（如有）+ 时间线表格 + 确认/退回按钮
   └── 点击 → 同 §4.2 流程 → 决策（advance/return） → archive 或 退回 hr_final
```

---

## 5. Build Order（Phase 拆分建议）

> 基于组件依赖图，从"无依赖"到"全依赖"逐层叠加。每个 phase 完成后系统都应是**可运行可演示**的。

```
依赖图：
  Phase 1 (settings/db/migration)
       ↓
  Phase 2 (state_store + flow_engine 骨架 + interrupt)  ← 端到端：API → graph → interrupt → resume
       ↓
  Phase 3 (auth/JWT + cookie + jti 黑名单)             ← 接入 token 鉴权
       ↓
  Phase 4 (通知 outbox + email_sender + APScheduler)    ← 邮件能发出去
       ├──→ Phase 5a (Next.js 骨架 + 一键登录页)
       │         ↓
       │      Phase 5b (NodeForm + 决策提交)
       │         ↓
       │      Phase 5c (HR Dashboard + 我的流程)
       │         ↓
       │      Phase 5d (申请人确认页 + 时间线)
       ↓
  Phase 6 (Mattermost sender + 双通道)
       ↓
  Phase 7 (并行节点 + reducer + fan-in)
       ↓
  Phase 8 (GLM 摘要 + 失败降级)
       ↓
  Phase 9 (seed 脚本 + 演示模式开关 + 超时扫描)
       ↓
  Phase 10 (Docker Compose + nginx + 部署到 192.168.2.44)
       ↓
  Phase 11 (E2E 测试 + 演示稿)
```

### 详细 Phase 表

| Phase | 内容 | 完成后可演示 | 关键依赖 |
|---|---|---|---|
| **P1 基建** | uv 项目 / pyproject.toml / Pydantic Settings / Postgres + Redis docker-compose / alembic 初始化 + 业务表 migration / `langgraph` schema 创建 SQL | `uvicorn app.main:app` 起得来，`/api/health` 200 | 无 |
| **P2 引擎骨架** | LangGraph state.py + graph.py + AsyncPostgresSaver + 2 个节点（apply + manager_review）+ interrupt() + Command(resume) + POST /api/flows + POST /api/flows/{id}/nodes/{id}/actions（先不鉴权）| curl 起流程 → 看到 waiting → curl 提交 advance → 推进 | P1 |
| **P3 鉴权** | JWT 签发 / decode / jti 黑名单（Redis）/ HttpOnly Cookie / POST /api/auth/exchange / role 校验 dep | curl 拿一个 token → exchange → cookie → 用 cookie 提交决策 | P2 |
| **P4 通知 outbox** | notification_outbox 表 + outbox_repo + email_sender（aiosmtplib + 演示模式覆写）+ APScheduler outbox_drain + 节点函数双写 outbox + 邮件模板（generic.html）| curl 起流程 → 10s 内 QQ 邮箱真的收到邮件，标题带角色前缀 | P3 |
| **P5a 前端骨架** | Next.js 15 init / Tailwind v4 / shadcn/ui / `output: export` / 一键登录页（flow/[id]/node/[id]）+ API client | 邮件点按钮 → 浏览器自动 exchange → 看到节点详情 | P4 |
| **P5b 决策表单** | NodeForm（说明只读 + 文本框 + 三按钮）+ POST actions + 成功/错误提示 | 邮件点按钮 → 填写 → 提交 → 自动收下一封 | P5a |
| **P5c Dashboard** | /my/flows（员工视角） + /hr/dashboard（HR 视角，列出所有流程 + 当前节点 + 卡点筛选） | HR 在浏览器看到所有流程进度 | P5b |
| **P5d 申请人确认页** | ApplicantConfirm 组件（时间线 + 摘要段 + 确认/退回）+ 申请人节点的特殊 view 接口 | 申请人邮件点按钮 → 看到所有节点结果时间线 | P5c |
| **P6 Mattermost** | mattermost_sender + Bot Token + outbox 二通道 + Interactive Message 卡片（先不接收回调，v1 链接跳转即可） | 邮件 + Mattermost 同时到达 | P4 |
| **P7 并行节点** | Annotated reducer / fan-out / fan-in / 4 个并行节点（device_return / access_revoke / knowledge_handover / finance_settle） | 起流程跑到并行段 → 4 个角色同时收到邮件 → 任意顺序处理 → 全部完成才进入 legal_sign | P5b |
| **P8 LLM 摘要** | glm_client + summarize_node_results + 申请人确认节点调用 + 失败降级（不抛、不阻塞） | 申请人邮件正文顶部出现 GLM 一段自然语言摘要 | P5d, P7 |
| **P9 Seed + 超时** | seed_demo_data.py（Mattermost + DB 双写 8 个账号）+ APScheduler timeout_scan + reminder outbox + APP_MODE=demo 切换测试 | 一键 seed → 一键起流程 → 全程演示模式邮件路由到 DEMO_INBOX | P7, P8 |
| **P10 部署** | Dockerfile（backend + nginx）+ docker-compose.yml + nginx.conf + entrypoint.sh（alembic upgrade + saver.setup + uvicorn）+ .env.example | `docker compose up -d` 在 192.168.2.44 一键起来 | P9 |
| **P11 测试 + 演示** | unit + integration + e2e ≥ 80% 覆盖 + 演示讲稿 + 录屏 | 面试可演示 | P10 |

**关键 sequencing 决策：**

- **P3 鉴权放在 P4 通知之前**：通知里要带 token 链接，token 签发能力必须先就绪
- **P5a 前端在 P4 之后**：必须先有真实邮件能点，前端开发才能闭环验证
- **P6 Mattermost 在 P5 之后**：邮件链路先打通完整闭环，Mattermost 是二通道增强；如果先做 Mattermost 会因为没前端无法验证「点击 → 登录 → 决策」
- **P7 并行节点放在 P5b 之后而不是更早**：单线流程跑通后再加并行复杂度，避免一开始就调 reducer/fan-in 问题
- **P8 LLM 必须最后**：和核心流程解耦，失败降级路径要先验证
- **P10 Docker 部署放最后**：开发期 docker-compose 起 PG/Redis 即可，FastAPI/Next 在本机跑迭代快；最后一步打镜像

---

## 6. 关键模块接口契约

### 6.1 节点函数签名（LangGraph）

```python
# 所有人工节点的统一签名
async def {node_name}_node(state: OffboardingState) -> dict:
    """
    返回值会被 reducer 合并到 state。
    必须幂等：interrupt() 抛 GraphInterrupt 后，节点会从头重跑。

    职责：
      1. 业务事务：upsert node_states + enqueue outbox (channels: email, mattermost)
      2. interrupt(payload) 挂起
      3. resume 后处理 decision，返回 dict 更新 state
    """
```

### 6.2 通知 Dispatcher API

```python
# notifications/dispatcher.py
async def dispatch_node_notification(
    session: AsyncSession,
    *,
    node_state_id: UUID,
    flow_id: UUID,
    assignee: User,
    role: str,
    template: str = "generic_node",
    extra_context: dict | None = None,
) -> list[OutboxRecord]:
    """事务内调用；返回 outbox 记录列表（已 INSERT，pending 状态）"""
```

### 6.3 Token Exchange 端点

```
POST /api/auth/exchange
Body: { "token": "eyJ..." }
Response 200: { "redirect_to": "/flow/.../node/...", "role": "manager", "name": "李四" }
Response 401: { "code": "TOKEN_INVALID" | "TOKEN_CONSUMED" | "TOKEN_EXPIRED" | "ASSIGNEE_MISMATCH" }
Side effect: Set-Cookie: session=...; HttpOnly; SameSite=Lax; Max-Age=86400
```

### 6.4 节点决策提交端点

```
POST /api/flows/{flow_id}/nodes/{node_id}/actions
Cookie: session
Body: {
  "action": "advance" | "return" | "reject",
  "result_text": "string (必填)",
  "reason": "string (action != advance 时必填)"
}
Response 200: { "next_node": "hr_initial", "current_assignee": "hr.alice", "status": "running" }
Response 409: { "code": "NODE_NOT_WAITING" | "STATE_CONFLICT" }
Response 403: { "code": "NOT_ASSIGNEE" | "ACTION_NOT_ALLOWED" }
```

### 6.5 节点视图端点

```
GET /api/flows/{flow_id}/nodes/{node_id}/view
Cookie: session
Response 200: {
  "node_name": "manager_review",
  "node_title": "上级审批",
  "node_description": "请审批...",
  "allowed_actions": ["advance", "reject"],
  "status": "waiting_human",
  "context": { ... },
  "timeline": [{ ... }]   // applicant_final_confirm 时填充
}
```

### 6.6 LangGraph 单例访问

```python
# flow_engine/graph.py
_graph: CompiledGraph | None = None

async def get_graph() -> CompiledGraph:
    """启动时构建，全局复用；线程安全（asyncio 单线程）"""
    global _graph
    if _graph is None:
        checkpointer = await init_checkpointer(settings.POSTGRES_DSN)
        _graph = build_standard_offboarding_graph().compile(checkpointer=checkpointer)
    return _graph
```

---

## 7. Scaling Considerations

| 规模 | 架构调整 |
|---|---|
| **演示 / < 10 并发流程** | 当前架构原样，单进程 uvicorn，APScheduler in-process |
| **生产小规模 / < 1k 并发流程** | uvicorn workers=2-4（但 APScheduler 需要切独立进程或加 leader 选举，否则多 worker 重复发送）；outbox drain 提到独立进程 |
| **生产中等规模 / 10k+ 流程** | 切 Celery + Redis broker（outbox 表仍保留作幂等保证）；FastAPI 与 Worker 分容器；Postgres 主从分离读写；Mattermost/SMTP 通道接入消息队列限速 |
| **企业级** | LangGraph Platform / LangSmith 托管；Postgres 分库（按 flow_template）；事件总线（Kafka）做跨系统集成 |

### 首先会断的环节

1. **APScheduler 多进程重复执行**：uvicorn workers > 1 时立即出问题，必须先解决（切独立 scheduler 容器或加 redis leader lock）
2. **同步 SMTP 阻塞**：QQ SMTP 5-10s 卡顿放大；outbox 模式已经规避
3. **LangGraph 单例锁竞争**：Python GIL + asyncio 单线程下，节点函数里有阻塞调用就拖慢整图；llm 调用必须 httpx async + 超时

---

## 8. Anti-Patterns

### Anti-Pattern 1: HTTP 路由内同步等 SMTP

**What people do:** 节点函数里直接 `await smtp.send_email(...)` 然后 return state。
**Why it's wrong:** QQ SMTP 偶尔 5-10s 延迟会卡住 graph 推进；SMTP 失败导致节点函数抛异常，graph 进入 error 状态，业务表已写但通知没发出。
**Do this instead:** outbox 模式，节点函数只 `INSERT INTO notification_outbox`，后台 worker drain。

### Anti-Pattern 2: 业务侧直接 SELECT LangGraph checkpoint

**What people do:** HR Dashboard 需要看流程状态，直接 `SELECT * FROM langgraph.checkpoints WHERE thread_id=...`。
**Why it's wrong:** schema 跟版本绑定（LangGraph 升级会变），数据是 pickle 二进制无法做 SQL 聚合，跨流程查询 N+1。
**Do this instead:** 业务表为唯一 source of truth，UI 全部走 `flow_instances` / `node_states`。

### Anti-Pattern 3: 在节点函数内调 `graph.ainvoke`

**What people do:** 节点函数想"主动触发下一步"，调 `graph.ainvoke(...)`。
**Why it's wrong:** 死锁（graph 在等当前节点 return，节点又在等 graph）；checkpointer 状态错乱。
**Do this instead:** 节点函数只 return state；推进交给条件边和上层 `services/node_service.py` 的 resume 调用。

### Anti-Pattern 4: 并行节点 state 字段不加 reducer

**What people do:** `class State(TypedDict): results: list[NodeResult]` —— 4 路并行各 append，最后只剩 1 条。
**Why it's wrong:** 默认 last-write-wins。
**Do this instead:** `Annotated[list[NodeResult], operator.add]`。

### Anti-Pattern 5: 用 `interrupt_before` + 在上游节点写表

**What people do:** 编译时 `interrupt_before=["manager_review"]`，然后在 `apply_node` 里写 `node_states("manager_review", waiting_human)`。
**Why it's wrong:** 职责拧巴，上游知道下游内部细节；并行场景下要在 fanout 节点写 4 份子节点的 state，违反 SRP；恢复后 manager_review 节点又跑一遍同样的"进入副作用"会重复发通知。
**Do this instead:** 用 dynamic `interrupt()`，每个节点自己写自己的 state（幂等 upsert）+ enqueue outbox（带唯一约束）。

### Anti-Pattern 6: jti 黑名单只存 Redis 不持久化审计

**What people do:** 一次性 token 只往 Redis SET。
**Why it's wrong:** Redis 重启 → 所有未消费 token 又能用了；合规审计无法回答"这个 token 谁什么时候用的"。
**Do this instead:** 演示阶段 Redis 够用（v1 OK）；生产加 PG `consumed_tokens` 表（jti + sub + flow_id + consumed_at + ip）。

### Anti-Pattern 7: Next.js 静态导出却写了 RSC / Server Action

**What people do:** 用 `async function Page()` 服务端 fetch / 用 `'use server'`。
**Why it's wrong:** `output: export` 不支持，build 失败或运行时 404。
**Do this instead:** 所有页面 `'use client'`，所有数据 fetch 在 useEffect 里走浏览器到 `/api/`。

### Anti-Pattern 8: alembic migration 里包含 langgraph schema

**What people do:** `alembic revision --autogenerate` 把 LangGraph 的 checkpoints 表也扫进去。
**Why it's wrong:** LangGraph 升级时 schema 会变，你的 migration 跟 LangGraph 自管的会冲突。
**Do this instead:** alembic env.py `include_object` 过滤掉 langgraph schema；`AsyncPostgresSaver.setup()` 单独跑（entrypoint.sh 里 alembic upgrade 之后）。

---

## 9. Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **SMTP smtp.qq.com:465 (SSL)** | aiosmtplib async；演示模式 dispatcher 覆写 recipient | QQ 强制 SSL（非 STARTTLS）；授权码非密码；连接复用减少 5s 握手开销 |
| **Mattermost http://192.168.2.44:8065** | httpx async；Bot Personal Access Token；POST /api/v4/posts | Interactive Message `actions` 字段 v1 只做跳转 URL，不接收回调 |
| **GLM API（智谱）** | httpx async；超时 10s；失败降级返回 None | 调用在申请人确认节点；失败不抛、不阻塞 graph |
| **Postgres** | asyncpg + SQLAlchemy 2.x async；连接池 max=20 | 业务 schema `app`，LangGraph schema `langgraph`，同 DB 不同 schema |
| **Redis** | redis-py async；连接池 max=10 | jti 黑名单（SETNX + EX）+ APScheduler jobstore（可选） |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| **router → service** | 直接 Python 函数调用 + Depends 注入 db_session | 服务层不知道 HTTP；测试时直接构造 session 注入 |
| **service → flow_engine** | `get_graph()` 拿单例，`ainvoke(initial_state)` 或 `ainvoke(Command(resume=...))` | 服务层是 LangGraph 的唯一调用方；节点函数不反向调服务层 |
| **service ↔ state_store** | repository 函数 + 显式 session 参数 | 所有 SQL 集中在 repo；service 编排事务 |
| **node 函数 → state_store** | 同 service 模式 | 节点函数从 graph 传入 contextvar 拿到 session_maker；事务在节点函数内 |
| **node 函数 → notification dispatcher** | dispatcher 写 outbox（事务内）；不直接调 SMTP | 解耦发送时机 |
| **APScheduler → service / dispatcher** | 直接函数调用 | scheduler 是进程内组件 |
| **nginx → flow-api** | HTTP 反代 | `/api/` `/ws/` 转发；其余 try_files |
| **frontend → backend** | fetch + credentials: 'include' | 同源（nginx 反代后），无 CORS |

---

## 10. 关键 Pitfall 速查（与 PITFALLS.md 重复，此处提架构相关）

1. **interrupt() 重跑副作用要幂等** —— 用 `INSERT ... ON CONFLICT DO NOTHING` 或 `UPSERT`，outbox 表加 `UNIQUE(flow_id, node_state_id, channel)`
2. **AsyncPostgresSaver 必须用 ainvoke，不能用 invoke** —— 混用会 hang（langgraph issue #1800）
3. **节点函数 return 不能 mutate 输入 state** —— 永远 return 新 dict，TypedDict 不是不可变的，但 reducer 假设是 immutable
4. **演示模式覆写要在 sender 而不是 dispatcher** —— `notifications.recipient` 字段必须存真实 assignee 邮箱（审计要），只在 SMTP 发送瞬间覆写到 DEMO_INBOX
5. **alembic + langgraph schema 必须隔离** —— include_object 过滤
6. **Cookie SameSite 设 Lax 不能 Strict** —— 邮件 → 浏览器跳转是 cross-site navigation，Strict 会丢 Cookie
7. **QQ SMTP 第一封邮件常常 5-10s 延迟** —— outbox + 后台 drain 模式是必需的，否则用户感受"系统卡死"
8. **Mattermost incoming webhook 与 Bot API 二选一** —— v1 推荐 Bot Token + POST /api/v4/posts（更通用），webhook 留作备用

---

## 11. Sources

### 高置信度（Context7-grade / 官方文档）

- [LangGraph Interrupts (官方)](https://docs.langchain.com/oss/python/langgraph/interrupts) — 动态 interrupt() 与静态 interrupt_before 对比
- [LangGraph use-graph-api (官方)](https://docs.langchain.com/oss/python/langgraph/use-graph-api) — TypedDict + Annotated reducer 语法
- [AsyncPostgresSaver API Reference](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver) — checkpointer 用法与 setup()
- [langgraph-checkpoint-postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/) — 包说明与 schema 信息
- [FastAPI Background Tasks (官方)](https://fastapi.tiangolo.com/tutorial/background-tasks/) — BackgroundTasks 限制
- [Next.js Dynamic Routes (官方)](https://nextjs.org/docs/app/building-your-application/routing/dynamic-routes) — 动态路由约束
- [Next.js useParams (官方)](https://nextjs.org/docs/app/api-reference/functions/use-params) — Client Component hook
- [Microservices.io Transactional Outbox](https://microservices.io/patterns/data/transactional-outbox.html) — outbox 模式权威定义

### 中置信度（社区，多源印证）

- [LangChain 官方博客 — Making it easier to build HITL with interrupt](https://www.langchain.com/blog/making-it-easier-to-build-human-in-the-loop-agents-with-interrupt) — interrupt 推荐用法
- [Next.js #79380 — CSR + dynamic route + output:export](https://github.com/vercel/next.js/issues/79380) — 静态导出 + 动态路由 workaround
- [Next.js #64660 — useParams in static export](https://github.com/vercel/next.js/discussions/64660) — useParams CSR 限制
- [LangGraph #1800 — async checkpointer with sync invoke hang](https://github.com/langchain-ai/langgraph/issues/1800) — ainvoke 必需性
- [DEV — Python Background Tasks Asyncio Traps 2026](https://dev.to/kaushikcoderpy/python-background-tasks-asyncio-traps-fastapi-celery-2026-381i) — BackgroundTasks 持久化局限
- [Leapcell — APScheduler vs Celery Beat](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat) — in-process scheduler 适用场景
- [OneUptime — JWT Token Blacklist with Redis 2026](https://oneuptime.com/blog/post/2026-03-31-redis-how-to-build-a-token-blacklist-for-jwt-revocation-with-redis/view) — Redis SETNX + TTL 模式
- [TestDriven.io — Dockerizing FastAPI with Postgres](https://testdriven.io/blog/fastapi-docker-traefik/) — entrypoint.sh + alembic 模式
- [Markaicode — LangGraph Parallel Fan-Out](https://markaicode.com/langgraph-parallel-fan-out-fan-in/) — reducer 实战

---

*Architecture research for: LangGraph + FastAPI + Next.js 状态机驱动的离职流程系统*
*Researched: 2026-05-16*
