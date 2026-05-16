---
phase: 01-langgraph-schema
plan: 03
subsystem: database
tags: [sqlalchemy, alembic, postgres, repository, schema, upsert]
requires:
  - phase: 01
    provides: [pyproject.toml 含 sqlalchemy/asyncpg/alembic 依赖]
provides:
  - 6 张业务表 ORM 模型（app schema）
  - Alembic 异步 migration（含 include_object 过滤 langgraph schema）
  - FlowRepository / NodeRepository / ActionRepository / UserRepository（含 upsert 幂等）
affects: [Plan 04（节点函数最终接 Repository）, Plan 05（health 检查 DB）, Plan 06（service 层调用 Repository）, Plan 07（E2E 校验业务表）]

tech-stack:
  added:
    - SQLAlchemy 2.0.49 declarative + async
    - Alembic 1.x async migration
  patterns:
    - PG ON CONFLICT (UNIQUE 列) DO UPDATE 实现 upsert 幂等
    - 双 schema 隔离 (app + langgraph)
    - alembic include_object 过滤 langgraph 防 autogenerate 误删

key-files:
  created:
    - backend/src/offboarding_flow/state_store/__init__.py
    - backend/src/offboarding_flow/state_store/enums.py
    - backend/src/offboarding_flow/state_store/models.py
    - backend/src/offboarding_flow/state_store/repositories.py
    - backend/src/offboarding_flow/state_store/session.py
    - backend/alembic.ini
    - backend/migrations/env.py
    - backend/migrations/script.py.mako
    - backend/migrations/versions/0001_create_app_schema_tables.py
    - backend/tests/test_state_store.py

key-decisions:
  - "用 Mapped/mapped_column SQLAlchemy 2.x 推荐风格"
  - "UNIQUE(flow_id, node_name) 是节点 upsert 幂等的 KEY（PITFALLS #16）"
  - "alembic version_table_schema=app（alembic_version 也放 app schema 不污染 public）"
  - "Repository 不主动 commit — 交给 service 层控制事务边界"
  - "Phase 1 测试不连真 DB（用模型 + 静态校验），真集成测试留 Plan 07 + 全流程冒烟"

patterns-established:
  - "Pattern: Repository 层 — 接收 AsyncSession 注入，提供 upsert/get/list/complete 接口"
  - "Pattern: alembic include_object 过滤 — PITFALLS #1 防范误删 LangGraph 表"

requirements-completed:
  - DEPLOY-01
  - DEPLOY-05

duration: 8min
completed: 2026-05-16
---

# Phase 1 Plan 03: 业务表 schema + Alembic + Repository

**6 张业务表（app schema）+ Alembic 异步 migration + 含 upsert 幂等的 Repository 层 — Phase 2 双写规范的业务侧承担方就位。**

## Performance

- Duration: ~8 min
- Tasks: 3
- Files modified: 10

## Accomplishments

1. **6 张 ORM 模型** — flow_instances / node_states / action_logs / users / notifications / notification_outbox（全部 app schema + UUID PK gen_random_uuid + TIMESTAMPTZ）
2. **关键约束**：node_states.UNIQUE(flow_id, node_name)（节点 upsert 幂等基础）+ notification_outbox.UNIQUE(flow_id, node_state_id, channel)（Phase 4 outbox 幂等）
3. **Alembic 异步 migration** — env.py include_object 过滤 langgraph schema（PITFALLS #1）+ version_table_schema=app
4. **migration 0001** — 完整建 6 表 + 创建 app schema + 索引（employee_id / status / assignee 等查询频繁列）
5. **Repository 层** — FlowRepository (create/get/list_all/mark_completed) + NodeRepository (upsert/get/list_by_flow/complete) + ActionRepository (create/list_by_flow) + UserRepository (upsert/get_by_username)
6. **session.py** — async engine 单例 + sessionmaker + connect_args server_settings search_path=app,public（CONTEXT §2 业务连接锁 search_path）

## Verification Results

- 14 个单元测试全通过（覆盖模型实例化 / enum 值 / UNIQUE 约束 / Repository 方法签名）
- `alembic script` 能离线读取 0001 migration
- Base.metadata.tables 正好 6 张表

## Next

Plan 06（API 业务集成）会把 Repository 接入 service 层 + API 端点。
