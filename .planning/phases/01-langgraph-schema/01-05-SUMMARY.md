---
phase: 01-langgraph-schema
plan: 05
subsystem: api
tags: [fastapi, pydantic-settings, lifespan, envelope, exception-handler, structlog, health]
requires:
  - phase: 01
    provides: [pyproject.toml 含 fastapi + pydantic-settings + structlog]
provides:
  - Pydantic Settings 全局配置（lru_cache 单例）
  - structlog 配置（dev colorized / prod JSON）
  - 全局响应 envelope {success, data, error, meta}
  - 全局 exception handler
  - GET /api/health 组件检查
  - FastAPI lifespan 串联 init_db / build_graph / dispose
affects: [Plan 06（业务路由通过 main.create_app 注册 + 用 envelope/exception handler）, Phase 2/3/4 所有新增 API 路由复用 envelope]

tech-stack:
  added:
    - fastapi 0.136.1 + Pydantic v2.13
    - structlog 25.x
    - asgi-lifespan（测试用）
  patterns:
    - lifespan 容错（DB 不通也启动）
    - APP_MODE 启动 warning 日志（PITFALLS #10）
    - lru_cache(get_settings) 单例

key-files:
  created:
    - backend/src/offboarding_flow/config.py
    - backend/src/offboarding_flow/main.py
    - backend/src/offboarding_flow/api/__init__.py
    - backend/src/offboarding_flow/api/envelope.py
    - backend/src/offboarding_flow/api/errors.py
    - backend/src/offboarding_flow/api/health.py
    - backend/src/offboarding_flow/utils/__init__.py
    - backend/src/offboarding_flow/utils/logger.py
    - backend/tests/test_api_health.py

key-decisions:
  - "lifespan 用 try/except 容错 — DB 不通不阻断启动（开发期友好），健康检查报 degraded"
  - "envelope.ok/err 返回 dict 不返回 Pydantic Generic — 避免 Generic 序列化复杂度"
  - "exception_handler 同时注册 Starlette HTTPException + FastAPI HTTPException + RequestValidationError + Exception 兜底"
  - "create_app 内 try import flows/nodes router — Plan 06 写完后自动挂载，本 Plan 单独可运行"

patterns-established:
  - "Pattern: 统一响应 envelope — 所有 4xx/5xx 走全局 handler 包成 {success,data,error,meta}"
  - "Pattern: 启动 warning 打印 APP_MODE — 防演示模式上线（PITFALLS #10）"

requirements-completed:
  - DEPLOY-01

duration: 7min
completed: 2026-05-16
---

# Phase 1 Plan 05: FastAPI 应用骨架

**FastAPI app + lifespan + 全局 envelope + 全局 exception handler + structlog + /api/health 组件检查 — Phase 1 Web 框架骨架。**

## Performance

- Duration: ~7 min
- Tasks: 3
- Files modified: 9

## Accomplishments

1. **config.py** — Pydantic Settings + lru_cache 单例 + computed_field postgres_dsn_sync（给 alembic offline）+ 启动 warning 打印 APP_MODE/VERSION/LOG_LEVEL（PITFALLS #10）
2. **utils/logger.py** — structlog 配置 + dev ConsoleRenderer (colorized) / prod JSONRenderer + uvicorn.access / sqlalchemy.engine 降噪
3. **api/envelope.py** — ok(data, meta) / err(message, meta) helper
4. **api/errors.py** — 4 个 exception handler（Starlette HTTPException + FastAPI HTTPException + RequestValidationError + Exception 兜底）
5. **api/health.py** — GET /api/health 检查 db (SELECT 1) + graph (singleton 状态) + redis (not_checked 留 Phase 3)
6. **main.py** — lifespan 容错串 init_db → build_graph → dispose；create_app 自动注册 flows/nodes routers（若 Plan 06 已写）
7. **测试** — 5 个用例全通过（含 404 / 405 envelope 校验）

## Verification Results

- pytest tests/test_api_health.py 5/5 pass
- /api/health 在 DB 不通时仍返回 200 status=degraded

## Next

Plan 06 在 Wave 3 实现业务路由（flows + nodes + service 层 + 双写规范）。
