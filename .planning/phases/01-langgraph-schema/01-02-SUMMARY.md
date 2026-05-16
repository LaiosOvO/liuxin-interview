---
phase: 01-langgraph-schema
plan: 02
subsystem: infra
tags: [docker, compose, postgres, redis, dockerfile, entrypoint]
requires: []
provides:
  - docker-compose.yml（生产）+ docker-compose.dev.yml（开发 override）
  - 多阶段 Dockerfile（uv builder + python 3.12-slim runtime）
  - entrypoint.sh（alembic → checkpointer.setup → uvicorn）
  - deploy/init-db.sql 创建双 schema (app + langgraph)
affects: [Plan 03（alembic 用 app schema）, Plan 04（checkpointer setup 入口）, Plan 06（API 部署）, Plan 07（dev_up.sh）, Phase 6（最终部署到 44）]

tech-stack:
  added:
    - docker compose v2 (Compose Spec)
    - postgres:16-alpine, redis:7-alpine
    - uv:0.10-python3.12-bookworm-slim builder image
    - python:3.12-slim-bookworm runtime image
  patterns:
    - 独立 postgres 容器（不复用 Mattermost / MinIO 的 PG 实例）
    - 端口 5433/6380 避免冲突
    - init-db.sql 通过 docker-entrypoint-initdb.d 在首次启动自动跑
    - 多阶段 Dockerfile（builder 含 uv，runtime 仅 venv + 源码）

key-files:
  created:
    - docker-compose.yml
    - docker-compose.dev.yml
    - deploy/init-db.sql
    - backend/Dockerfile
    - backend/.dockerignore
    - backend/entrypoint.sh

key-decisions:
  - "用 uv:0.10-python3.12-bookworm-slim AS builder（uv 镜像最新 0.10）"
  - "runtime 用 python:3.12-slim-bookworm（不用 alpine — PITFALLS 提到 alpine 跑 Python 编译麻烦）"
  - "POSTGRES_PASSWORD:? 语法强制启动失败"
  - "init-db.sql 创建 4 个 schema (app + langgraph + app_test + langgraph_test) — 测试用 schema 留 Plan 03 + 后续测试用"
  - "Compose 没用废弃的 'version: x.x' 顶级字段"
  - "Phase 1 不上 nginx / web 容器（Phase 6 才完整部署）"

patterns-established:
  - "Pattern: 启动顺序（DEPLOY-05）— alembic 跑业务 migration（app schema）→ checkpointer.setup 自管 langgraph schema → uvicorn"
  - "Pattern: dev/prod 分离 — docker-compose.dev.yml override 挂源码 + --reload"

requirements-completed:
  - DEPLOY-01
  - DEPLOY-05

duration: 4min
completed: 2026-05-16
---

# Phase 1 Plan 02: Docker 编排骨架

**Docker Compose 三服务（postgres/redis/flow-api）+ 多阶段 Dockerfile + entrypoint 串联 alembic + checkpointer.setup + uvicorn — Phase 1 部署 192.168.2.44 的容器基座就位。**

## Performance

- Duration: ~4 min
- Tasks: 3
- Files modified: 6

## Accomplishments

1. **docker-compose.yml**（生产）— 三服务齐备 + healthcheck + restart=unless-stopped + 独立 offboarding-net + POSTGRES_PASSWORD 必填语法
2. **docker-compose.dev.yml**（开发 override）— 源码 volume mount + uvicorn --reload + DEBUG log
3. **deploy/init-db.sql** — 创建 app/langgraph/app_test/langgraph_test 4 schema + 设 flow 角色 search_path
4. **多阶段 Dockerfile** — uv builder（缓存依赖层）+ python:3.12-slim-bookworm runtime；ENTRYPOINT 串 entrypoint.sh
5. **entrypoint.sh** — 顺序 alembic upgrade head → python -m offboarding_flow.flow_engine.checkpointer --setup → exec uvicorn

## Verification Results

- `POSTGRES_PASSWORD=test docker compose config` 渲染正常（三服务 + 网络 + healthcheck 全部正确）
- entrypoint.sh 有 +x 权限
- Plan 07 的 smoke_test.sh 会真起容器验证

## Next

Plan 03（business schema） / Plan 04（LangGraph 引擎） / Plan 05（FastAPI app）三个并行进入 Wave 2。
