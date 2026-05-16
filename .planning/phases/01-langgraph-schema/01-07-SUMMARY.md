---
phase: 01-langgraph-schema
plan: 07
subsystem: testing
tags: [e2e, smoke, dev-tools, scripts]
requires:
  - plan: 02
    provides: [docker compose 编排]
  - plan: 06
    provides: [4 业务 API 端点]
provides:
  - backend/tests/e2e/ 骨架 + Phase 1 冒烟用例 + Phase 2+ 场景清单占位
  - frontend/tests/e2e/ Phase 5 占位
  - scripts/dev_up.sh + scripts/smoke_test.sh
  - pyproject.toml e2e marker（默认 skip）
  - CHANGELOG Phase 1 Complete 段
affects: [Phase 2+ 在 backend/tests/e2e/ 追加用例, Phase 5 在 frontend/tests/e2e/ 落 Playwright spec, Phase 6 部署到 44 后跑 smoke_test.sh]

tech-stack:
  added:
    - shell scripts（dev_up + smoke_test）
  patterns:
    - pytest -m e2e marker + addopts 默认 skip（CI 不连真容器）
    - OFFBOARDING_E2E_BASE_URL 环境变量启用 E2E
    - python -m json.tool 在 shell 里输出格式化 JSON

key-files:
  created:
    - backend/tests/e2e/__init__.py
    - backend/tests/e2e/test_full_flow.py
    - backend/tests/e2e/README.md
    - frontend/tests/e2e/.gitkeep
    - frontend/tests/e2e/README.md
    - scripts/dev_up.sh
    - scripts/smoke_test.sh
  modified:
    - backend/pyproject.toml（加 e2e marker + addopts）
    - CHANGELOG.md（Phase 1 Complete 段）

key-decisions:
  - "E2E 默认 skip — pyproject.toml addopts = -m 'not e2e'，env OFFBOARDING_E2E_BASE_URL 启用"
  - "smoke_test.sh 用 sh 不用 bash（兼容 alpine / 任意 POSIX shell）"
  - "前端 E2E 仅占位 — Phase 5 才落 Playwright spec（用 webapp-testing skill）"
  - "演示模式 11 场景在 README 列清单，Phase 2+ 实现"

patterns-established:
  - "Pattern: E2E 测试默认 skip + 环境变量启用 — CI 友好"
  - "Pattern: shell smoke + pytest E2E 互补 — shell 给人看，pytest 给 CI/agent 跑"

requirements-completed: []

duration: 5min
completed: 2026-05-16
---

# Phase 1 Plan 07: E2E 骨架 + 冒烟脚本

**E2E 测试目录骨架 + 手动冒烟脚本 + CHANGELOG Phase 1 完成段 — Phase 1 整体可演示可验证。**

## Performance

- Duration: ~5 min
- Tasks: 3
- Files modified: 8

## Accomplishments

1. **backend/tests/e2e/test_full_flow.py** — Phase 1 冒烟用例（health 200 + create_flow + advance + 业务表/checkpoint 一致）+ docker restart 恢复占位
2. **backend/tests/e2e/README.md** — 演示模式 11 场景清单（CLAUDE.md §2.1）+ 怎么跑指引
3. **frontend/tests/e2e/** 占位 + README（Phase 5 才填 Playwright spec）
4. **scripts/dev_up.sh** — 一键起容器 + 等 healthcheck
5. **scripts/smoke_test.sh** — health → create_flow → list_nodes → advance → 重读 5 步冒烟
6. **pyproject.toml** — markers = ["e2e: ..."] + addopts = "-m 'not e2e'"（CI 默认 skip）
7. **CHANGELOG.md** — Phase 1 Complete 段含完整交付清单 + 下一步指引

## Verification Results

- 所有脚本可执行（+x 权限）
- pytest 默认 collect 35 个测试 + deselected 3 个 e2e
- Phase 1 7 个 Plan 全部完成

## Next

Phase 2（双写规范完整化 + 8 节点扩展 + 并行 fan-out + 申请人最终确认 + 全流程聚合邮件 schema）。
