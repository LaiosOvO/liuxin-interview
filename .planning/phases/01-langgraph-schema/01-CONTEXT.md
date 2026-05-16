# Phase 1: 基建 + LangGraph 骨架 + 业务表 schema - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** `--auto`（从 PRD v0.4 / SUMMARY.md / ROADMAP.md + 用户即时补充约束直接抽取，未走 4 问题深挖循环）

<domain>
## Phase Boundary

**交付目标**：跑通**最小可运行的状态机骨架** — 一个 FastAPI 进程托管 LangGraph 引擎，业务表与 PostgresSaver checkpoint 同库不同 schema 双写；实现 2 个最小节点（`apply` + `manager_review`）+ 3 个最小 API 端点，配合 Docker Compose 在目标服务器 `192.168.2.44` 跑起来；进程崩溃后能从最近 checkpoint 恢复。

**Phase 1 必须交付：**
1. uv 项目骨架（pyproject.toml + lock 文件）
2. PostgreSQL 16-alpine 容器（offboarding 专属实例）+ Redis 7-alpine 容器，部署到 `192.168.2.44`
3. 业务 schema (`app`) + LangGraph schema (`langgraph`) 双 schema 隔离
4. Alembic async migration（业务表 6 张）
5. LangGraph StateGraph + AsyncPostgresSaver + 2 个最小节点 + dynamic `interrupt()`
6. FastAPI 3 端点（health / 创建流程 / 提交决策）
7. `.gitignore` + `.env.example` + pre-commit gitleaks
8. 业务表双写规范的最小版（详细规范留到 P2）

**Phase 1 不交付**（明确推到对应 phase）：
- 鉴权（Phase 3）
- 通知 / 邮件 / Mattermost Bot 入口 / AI 报告（Phase 4）
- 其他 8 个节点 + 申请人最终确认 + 并行 fan-out（Phase 2）
- 前端（Phase 5）
- 自动节点演示（Phase 4.5）
- nginx / 完整部署 / 超时扫描（Phase 6）

**Phase 1 验收**（PRD §10.2 + ROADMAP §Phase 1 Success Criteria）：
- `docker compose up -d` 在 `192.168.2.44` 启动全部服务无 error
- `curl http://192.168.2.44:8000/api/health` 返回 200
- `POST /api/flows {"employee_id":"zhang.san"}` 创建流程并自动推进到 `manager_review` 节点 → 状态 `waiting_human`
- `POST /api/flows/{id}/nodes/{nid}/actions {"action":"advance","result_text":"..."}` 推进 → manager_review 节点 done（Phase 1 在 manager_review 后即结束流程，因为下游节点 P2 才实现）
- `docker compose restart flow-api` 后流程进度无丢失（重启后状态仍是 waiting_human / done）
- 业务表 `flow_instances` / `node_states` / `action_logs` 与 LangGraph checkpoint 数据一致

</domain>

<decisions>
## Implementation Decisions

### 1. 部署目标与数据库策略（用户即时确认）

**用户原话**："数据库用 psql 然后直接部署上去就行了 44 上面"

**决定**：
- **数据库引擎**：PostgreSQL 16-alpine（不是 mysql / sqlite）— "psql" 在这里指 PostgreSQL
- **数据库实例**：在 `docker-compose.yml` 起**独立的 `offboarding-postgres` 容器**部署到 `192.168.2.44`，**不复用现有 Mattermost / MinIO 等其他业务的 PG 实例**
  - 理由：部署边界清晰；schema 名 `app` / `langgraph` 在独占实例里不会撞名；演示完可干净删除
  - 端口：宿主机 `5433`（避免与系统默认 `5432` 冲突）
  - Volume：`/data/offboarding/postgres-data` 持久化
  - 网络：容器间走 docker network；外部连接走 `192.168.2.44:5433`
- **Phase 1 直接部署到 192.168.2.44**（不在本地开发环境跑）
  - 开发期可用 `docker compose -f docker-compose.dev.yml up`（本地 mac），但 Phase 1 的交付验收**必须**在 `192.168.2.44` 上做
  - 部署方式：`docker compose --env-file .env up -d`（在 44 上执行）
- **Redis 同样独立容器** `offboarding-redis`（端口 6380）

### 2. 双 schema 隔离方案（ARCHITECTURE §3 Pattern 3）

- 同一 `offboarding-postgres` 实例下创建 2 个 schema：
  - `app` — 业务表（flow_instances / node_states / action_logs / notifications / notification_outbox / users）
  - `langgraph` — LangGraph checkpoint 表（由 `AsyncPostgresSaver.setup()` 自管，**不入 alembic**）
- 业务连接用 `DSN postgresql+asyncpg://...?options=-csearch_path%3Dapp,public` 把 search_path 锁到 `app`
- LangGraph 连接用 `AsyncPostgresSaver(conninfo, schema_name="langgraph")`（psycopg 3 + `autocommit=True + row_factory=dict_row + prepare_threshold=0`）
- alembic env.py 必须 `include_object` 过滤 `schema == 'langgraph'`（防 autogenerate 误删 LangGraph 表，PITFALLS #1）
- entrypoint.sh 顺序：`alembic upgrade head` → `await checkpointer.setup()` → `uvicorn`

### 3. 项目结构（uv src layout）

```
hr/
├── backend/
│   ├── pyproject.toml              # uv + 所有依赖
│   ├── uv.lock
│   ├── alembic.ini
│   ├── Dockerfile                  # 多阶段（uv builder + python:3.12-slim-bookworm runtime）
│   ├── entrypoint.sh
│   ├── src/
│   │   └── offboarding_flow/
│   │       ├── __init__.py
│   │       ├── main.py              # FastAPI app
│   │       ├── config.py            # Pydantic Settings
│   │       ├── api/                 # FastAPI routes
│   │       │   ├── __init__.py
│   │       │   ├── health.py
│   │       │   ├── flows.py
│   │       │   └── nodes.py
│   │       ├── flow_engine/         # LangGraph 引擎
│   │       │   ├── __init__.py
│   │       │   ├── state.py         # OffboardingState TypedDict
│   │       │   ├── graph.py         # StateGraph builder + 全局单例
│   │       │   ├── nodes/
│   │       │   │   ├── __init__.py
│   │       │   │   ├── apply.py
│   │       │   │   └── manager_review.py
│   │       │   └── checkpointer.py  # AsyncPostgresSaver 工厂
│   │       ├── state_store/         # 业务表 Repository
│   │       │   ├── __init__.py
│   │       │   ├── models.py        # SQLAlchemy 2.x ORM
│   │       │   ├── session.py       # async session 工厂
│   │       │   ├── repositories.py  # flow_repository, node_repository, action_repository
│   │       │   └── enums.py
│   │       ├── services/
│   │       │   ├── __init__.py
│   │       │   ├── flow_service.py
│   │       │   └── node_service.py
│   │       └── utils/
│   │           ├── __init__.py
│   │           └── logger.py        # structlog
│   ├── migrations/                  # alembic
│   │   ├── env.py                   # 含 include_object 过滤 langgraph schema
│   │   ├── versions/
│   │   └── script.py.mako
│   ├── scripts/
│   │   └── seed_demo_data.py        # Phase 1 仅占位骨架，Phase 4 完善
│   └── tests/
│       ├── conftest.py              # async db fixture, loop_scope=session
│       ├── test_flow_engine.py
│       ├── test_api.py
│       └── test_state_store.py
├── docker-compose.yml               # 生产部署（无 volume mount，restart=always）
├── docker-compose.dev.yml           # 本地开发 override（volume mount + auto-reload）
├── .env.example
├── .gitignore
└── .pre-commit-config.yaml          # gitleaks + ruff + mypy + check-yaml
```

### 4. LangGraph 编程模型（采纳 SUMMARY R3 修订）

- **dynamic `interrupt()` + `Command(resume=...)`**，不要 `interrupt_before` compile 参数
- 节点函数模板（伪代码）：

```python
async def manager_review_node(state: OffboardingState) -> dict:
    # 1. 幂等性判断（PITFALLS #16）— interrupt 抛 GraphInterrupt 后节点会重跑
    node_state = await node_repo.upsert(
        flow_id=state["flow_id"],
        node_name="manager_review",
        status="waiting_human",
        assignee=lookup_manager(state["employee_id"]),
    )
    # 2. 挂起等用户决策
    decision = interrupt({
        "node_name": "manager_review",
        "node_title": "上级审批",
        "node_description": "请审批此离职申请并填写意见",
        "assignee": node_state.assignee,
    })
    # 3. 收到决策后处理
    return {
        "current_action": decision["action"],
        "node_results": [{
            "node_name": "manager_review",
            "result_text": decision["result_text"],
            "actor": decision["actor"],
            "completed_at": now(),
        }],
    }
```

- API 层恢复（伪代码）：

```python
@router.post("/flows/{flow_id}/nodes/{node_id}/actions")
async def submit_action(flow_id, node_id, body):
    # 1. 业务事务：写 action_log + 更新 node_states
    async with db.begin():
        await action_repo.create(flow_id, node_id, body)
        await node_repo.complete(node_id, body.result_text)
    # 2. 提交事务 → 才 invoke LangGraph（ARCHITECTURE §3 Pattern 1）
    await graph.ainvoke(
        Command(resume={
            "action": body.action,
            "result_text": body.result_text,
            "actor": body.actor,
        }),
        config={"configurable": {"thread_id": str(flow_id)}},
    )
    return {"ok": True}
```

### 5. State 结构（TypedDict + Annotated reducer）

```python
from typing import TypedDict, Annotated
from operator import add

class NodeResult(TypedDict):
    node_name: str
    result_text: str
    actor: str
    completed_at: str  # ISO 8601

class OffboardingState(TypedDict):
    flow_id: str            # UUID4
    employee_id: str        # 离职员工 username
    current_action: str     # advance / return / reject（最近一次决策）
    node_results: Annotated[list[NodeResult], add]   # ⚠️ 漏 reducer 会 last-write-wins 静默丢数据
    context: dict           # 流程上下文（员工信息等）
```

### 6. API 端点（Phase 1 最小集，无鉴权）

| 方法 | 路径 | 功能 |
|------|------|------|
| GET | `/api/health` | health check（返回 db / redis / graph 状态）|
| POST | `/api/flows` | 创建流程实例 → `graph.ainvoke` 推进到第一个 interrupt |
| GET | `/api/flows/{flow_id}` | 查询流程状态（读业务表，**不读 LangGraph checkpoint**） |
| GET | `/api/flows/{flow_id}/nodes` | 列出该流程所有 node_states |
| POST | `/api/flows/{flow_id}/nodes/{node_id}/actions` | 提交三态决策 → `graph.ainvoke(Command(resume=...))` |

**统一响应 envelope**（用户全局规则 patterns.md）：
```json
{
  "success": true,
  "data": {...},
  "error": null,
  "meta": {...}
}
```

### 7. 业务表 schema（alembic 第一个 migration）

按 PRD §6.1 落 6 张表（Phase 1 完整建表，但 Phase 1 实际只用其中 3-4 张）：

| 表 | Phase 1 使用 |
|---|---|
| `flow_instances` | ✓ |
| `node_states` | ✓ |
| `action_logs` | ✓ |
| `users` | ✓（最小：username / email / role） |
| `notifications` | 建表，Phase 4 使用 |
| `notification_outbox` | 建表，Phase 4 使用 |

关键 column 约束：
- 所有 `id` 用 `uuid4()` 默认值（PITFALLS #17 防自增 ID 在并行节点冲突）
- `node_states.result_text TEXT NULL`
- `flow_instances.context JSONB NOT NULL DEFAULT '{}'`
- `node_states.status` enum (`pending / waiting_human / in_review / done / rejected / returned`)
- 所有时间用 `TIMESTAMP WITH TIME ZONE`

### 8. 测试约定

- `pytest-asyncio` mode = `auto`，fixture `loop_scope=session`（PITFALLS #23）
- `polyfactory` 生成 OffboardingState / NodeState 等测试数据
- 测试 DB：独立 schema `app_test` / `langgraph_test`，每个测试 truncate 而非 drop
- httpx.AsyncClient + asgi-lifespan 做 API 集成测试
- 覆盖率门槛 80%（用户全局 testing.md）
- 关键测试用例：
  - test_graph_advance: 起流程 → advance → 推进到下一节点
  - test_graph_recover: 起流程 → 模拟 docker restart → 重启后再 advance 仍能继续
  - test_double_write_consistency: 业务表 + checkpoint 两边状态一致
  - test_idempotency: 同一个 advance 调两次（模拟 interrupt 重跑）业务表不重复写
  - test_state_reducer: node_results 多次写不丢失

### 9. Pre-commit + 工具链（第一个 commit 之前必须）

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, sqlalchemy[mypy]]
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: no-commit-to-branch
        args: [--branch, main]
```

### 10. Docker 编排（Phase 1 最小版）

**docker-compose.yml**（生产部署到 44）：

```yaml
services:
  offboarding-postgres:
    image: postgres:16-alpine
    container_name: offboarding-postgres
    environment:
      POSTGRES_USER: flow
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: offboarding
    ports:
      - "5433:5432"
    volumes:
      - /data/offboarding/postgres-data:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U flow -d offboarding"]
      interval: 5s
      timeout: 3s
      retries: 5

  offboarding-redis:
    image: redis:7-alpine
    container_name: offboarding-redis
    ports:
      - "6380:6379"
    volumes:
      - /data/offboarding/redis-data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s

  flow-api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: offboarding-flow-api
    ports:
      - "8000:8000"
    environment:
      POSTGRES_DSN: postgresql+asyncpg://flow:${POSTGRES_PASSWORD}@offboarding-postgres:5432/offboarding
      LANGGRAPH_PG_CONNINFO: postgres://flow:${POSTGRES_PASSWORD}@offboarding-postgres:5432/offboarding
      REDIS_URL: redis://offboarding-redis:6379/0
      APP_MODE: ${APP_MODE:-demo}
    depends_on:
      offboarding-postgres:
        condition: service_healthy
      offboarding-redis:
        condition: service_healthy
    restart: unless-stopped
```

**docker-compose.dev.yml**（本地 mac 开发 override）：

```yaml
services:
  flow-api:
    volumes:
      - ./backend/src:/app/src   # auto-reload
    command: uvicorn offboarding_flow.main:app --host 0.0.0.0 --port 8000 --reload
```

**Phase 1 不上 nginx / web 容器**（Phase 6 才完整部署）。

### 11. 环境变量（.env / .env.example）

Phase 1 必需：
```env
APP_MODE=demo
POSTGRES_PASSWORD=changeme_in_real_env
POSTGRES_DSN=postgresql+asyncpg://flow:${POSTGRES_PASSWORD}@offboarding-postgres:5432/offboarding
LANGGRAPH_PG_CONNINFO=postgres://flow:${POSTGRES_PASSWORD}@offboarding-postgres:5432/offboarding
REDIS_URL=redis://offboarding-redis:6379/0
LOG_LEVEL=INFO
```

Phase 1 暂不需要（占位）：
- SMTP_* (Phase 4)
- MATTERMOST_* (Phase 4)
- GLM_API_KEY (Phase 4)
- JWT_SECRET (Phase 3)
- DEMO_INBOX (Phase 4)

### 12. 错误处理 + 日志

- structlog JSON 输出 + colorized dev mode
- 节点函数失败：raise Exception，由 LangGraph 引擎处理 retry / interrupt
- API 失败：FastAPI exception handler → 统一 envelope 返回 4xx/5xx
- DB 连接失败：startup 时 retry 5 次后 fail fast（不要 silent fallback）
- Phase 1 不做 alert/告警接入（Phase 6 才接）

### 13. 凭证安全

- `.env` 在 `.gitignore` 已就绪 ✓
- `.env.example` 不含真值（占位 `changeme_in_real_env`）
- pre-commit gitleaks 防漏（必须装）
- 部署到 44 时 `.env` 文件不上 git，scp 或 vault 注入
- PostgreSQL 密码用强密码（部署前 `openssl rand -base64 24` 生成）

### Claude's Discretion

下列细节由 Claude 在 implement 时自行决定，不需要回头问用户：

- ruff / mypy 的具体规则配置（用 ruff default + 适度 strict）
- 数据库连接池大小（默认 min_size=5, max_size=20）
- structlog 输出格式细节（INFO 用 colorized renderer，WARN+ 用 JSON）
- pytest-asyncio 子配置项
- Dockerfile 多阶段的层数 / 缓存策略（保证 < 200MB final image）
- alembic 命名约定 / 版本号格式
- FastAPI 路由依赖注入的 scope（默认 request）
- structlog `processors` 链
- `pyproject.toml` 的 `[tool.uv]` 配置细节
- `OffboardingState` 中除了 4 个核心字段外是否再加辅助字段
- Repository 是否分 abstract base + concrete impl（推荐：v1 直接 concrete，无 abstract）

</decisions>

<specifics>
## Specific Ideas

- **用户原话**："1创建一个"离职案件"数据记录 / 2设置至少3个角色 / 3 设计至少5个任务步骤 / 4给每个任务设置状态 / 5模拟AI根据当前状态输出下一步 / 6模拟任务逾期或证据缺失 / 7输出后台报告 / 8标出哪些动作AI不能做必须真人确认 / 9如候选人能力强演示API/Webhook/RPA自动动作"
  - 评分点 #1-#4 在 Phase 1 范围内（最小 2 节点 + 案件记录 + 状态枚举）
  - 评分点 #5-#9 在 Phase 4 / 4.5（本 Phase 不实现，但 schema 要预留 — node_results / status 字段已包含足够信息让 AI 报告使用）

- **用户原话**："具体简单来说就是在 mattermost能@bot 启动离职，然后能输出这些东西"
  - Phase 4 落地，本 Phase 不实现，但 `POST /api/flows` 端点要做成**Phase 4 Bot 直接复用**的形式（不要把入参绑死成 "通过前端表单提交"），方便 Bot 直接调

- **用户原话**："数据库用 psql 然后直接部署上去就行了 44 上面"
  - 已映射到决策 #1（独立 postgres 容器 + 部署 192.168.2.44 + 端口 5433）

- 演示场景：第一次启动后通过 `curl POST /api/flows {"employee_id":"zhang.san"}` 起流程 → 看到 `node_states` 里出现 `manager_review = waiting_human` → `curl POST /api/flows/{id}/nodes/{nid}/actions {"action":"advance","result_text":"同意"}` → 看到节点 done

- 设计参考：流程引擎流派（Camunda / Temporal / LangGraph），不是业务系统流派（Workday / SAP）— PRD §1.2 + Core Value 明确

</specifics>

<deferred>
## Deferred Ideas

下列点在 Phase 1 讨论中浮现，但属于其他 phase，**不在此 phase 实现**，已记录避免遗失：

- **鉴权 / JWT / Cookie 一键登录** → Phase 3
- **邮件 / Mattermost 通知 / outbox 模式** → Phase 4
- **AI 推理下一步 / AI 后台报告 / GLM 接入** → Phase 4
- **Mattermost @bot 入站命令解析（start / report / suggest 等）** → Phase 4
- **任务逾期检测 + 证据缺失检测** → Phase 4（检测逻辑）+ Phase 6（定时扫描 job）
- **AutoNode 自动节点 + mock-archive-service** → Phase 4.5（加分项）
- **前端 Next.js 静态导出 + 一键登录页 / HR Dashboard / 申请人确认页** → Phase 5
- **完整 nginx 反代 + 静态前端 + WebSocket 透传** → Phase 6
- **演示 runbook / E2E / 录屏 / 讲稿** → Phase 6
- **超时扫描 APScheduler job / dev-reset.sh / cleanup_old_checkpoints.py** → Phase 6
- **其他 8 节点 + 5 并行节点 + 申请人最终确认节点** → Phase 2
- **`scripts/recover_from_db.py` 工具** → Phase 2
- **业务表双写规范的失败补偿 + alert 触发** → Phase 2 完善（Phase 1 只做最小双写）

</deferred>

---

*Phase: 01-langgraph-schema*
*Context gathered: 2026-05-16 (auto mode from PRD v0.4 + SUMMARY.md + user constraints)*
