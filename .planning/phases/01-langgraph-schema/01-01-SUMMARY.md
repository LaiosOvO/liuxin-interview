---
phase: 01-langgraph-schema
plan: 01
subsystem: infra
tags: [uv, pyproject, pre-commit, gitleaks, ruff, mypy, pydantic-settings, structlog]
requires: []
provides:
  - backend/ uv 项目骨架（src layout）
  - 完整 v1 依赖（langgraph / fastapi / sqlalchemy 2 async / psycopg 3 / asyncpg / structlog / pydantic v2 / pytest）
  - pre-commit hooks（gitleaks 强制 + ruff + mypy + 系统钩子）
  - 完整 .env.example（Phase 1 + 占位所有 Phase 3/4 字段）
  - pytest 全局 fixture（loop_scope=session）
affects: [所有后续 plan，提供 Python 运行环境与代码质量基线]

tech-stack:
  added:
    - uv 0.10.4 包管理
    - fastapi 0.136.1, sqlalchemy 2.0.49, langgraph (latest), structlog 25.x, pydantic 2.13.x
    - pre-commit 4.6 + gitleaks v8.21 + ruff v0.8 + mypy v1.13
  patterns:
    - src/ layout（避免 implicit namespace package + 让测试导入路径清晰）
    - lru_cache(get_settings) 单例
    - 所有凭证占位 changeme_in_real_env

key-files:
  created:
    - backend/pyproject.toml
    - backend/uv.lock
    - backend/.python-version
    - backend/src/offboarding_flow/__init__.py
    - backend/tests/__init__.py
    - backend/tests/conftest.py
    - .pre-commit-config.yaml
  modified:
    - .gitignore（追加 backend/.venv / coverage / .claude/settings.local.json）
    - .env.example（重写：Phase 1 段在前 + 凭证全 changeme_in_real_env）
    - CHANGELOG.md（[Unreleased] / Added）

key-decisions:
  - "用 hatchling 做 build-backend（uv init 默认推荐 + 配置最简单）"
  - "ruff target-version=py312, line-length=100, select B/UP/SIM/RUF 提高代码质量"
  - "mypy strict=false（启用 strict 会让 SQLAlchemy 2 mapped_column 报大量误报）"
  - "pre-commit ruff/mypy 限定 backend/ 路径（避免扫 .planning/ / migrations/versions）"

patterns-established:
  - "Pattern: src/ layout — Python 包代码放 src/，pyproject.toml/tests 在根，避免 import 路径混乱"
  - "Pattern: pre-commit gitleaks 强制 — 任何凭证泄露在 commit 前拦截"

requirements-completed:
  - DEPLOY-04

duration: 6min
completed: 2026-05-16
---

# Phase 1 Plan 01: 项目骨架 + 工具链

**Phase 1 第一个 commit 之前的基线就位 — backend/ 完整 uv 项目结构 + 所有 v1 依赖 + pre-commit gitleaks 强制 + 凭证全占位。**

## Performance

- Duration: ~6 min
- Tasks: 3
- Files modified: 7

## Accomplishments

1. **backend/pyproject.toml** 落地，含 [project]/[tool.uv]/[tool.ruff]/[tool.mypy]/[tool.pytest.ini_options] 完整配置；uv sync 装 90+ 个依赖（含 langgraph + fastapi + sqlalchemy 2 async + psycopg 3 + asyncpg + structlog + pydantic v2 + pytest 全家桶）
2. **pre-commit hooks** 装上 — gitleaks v8.21 + ruff v0.8 + mypy v1.13 + 系统钩子（check-yaml / trailing-whitespace / no-commit-to-branch=main）
3. **.env.example** 重写 — Phase 1 段（POSTGRES_PASSWORD / POSTGRES_DSN / LANGGRAPH_PG_CONNINFO / REDIS_URL）+ 完整 Phase 3/4 字段占位；所有凭证用 `changeme_in_real_env`
4. **conftest.py** 配置 pytest-asyncio mode=auto + loop_scope=session（防 PITFALLS #23 测试 hang）

## Verification Results

- `uv sync --all-extras` 成功（90+ 包）
- 关键 import 校验通过：`langgraph / fastapi 0.136.1 / sqlalchemy 2.0.49 / pydantic 2.13.4` 全部可 import
- `uv run pytest --collect-only` 0 错误（无测试是正常的，Plan 03+ 才加测试）

## Next

Plan 02（Docker 编排）已在 Wave 1 并行进行；Plan 03/04/05 在 Wave 2 开始。
