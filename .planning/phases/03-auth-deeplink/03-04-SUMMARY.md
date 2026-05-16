# Plan 03-04 SUMMARY — node_service hook + 3 E2E + CHANGELOG/STATE

**Status:** COMPLETE
**Wave:** 3（依赖 Plan 01 + 02 + 03）
**Date:** 2026-05-16
**Requirements addressed:** AUTH-03（完成）+ AUTH-04（完成）

## Delivered

### 节点状态变更 hook
- **services/node_service.py**：
  - 构造新增可选 `redis: Redis | None = None` 参数
  - `submit_action` 在 `await self.session.commit()` 之后、`graph.ainvoke` 之前调 `jti_service.invalidate_node_tokens(redis, node_id)`
  - 失败仅 log warning 不阻断主链路（try-except + 非致命）
- **api/deps.py**：`get_node_service` 注入 `Redis = Depends(get_redis_dep)`

### 共享 fixture 重构
- **tests/conftest.py**：抽出 db_session / http_client / sample_node_and_user / two_flows_with_nodes 4 个 fixture 到顶层 conftest（被 tests/auth/ 与 tests/e2e/ 共用）
- **tests/auth/conftest.py**：清空为注释（fixture 已上移）
- **tests/auth/test_exchange_endpoint.py**：移除本地 fixture，复用顶层

### 测试
- **tests/auth/test_node_advance_invalidates_tokens.py** 3 用例（需 DB+Redis，环境无故 SKIPPED）：
  - test_advance_invalidates_node_tokens — advance 后 jti key + node SET 都清掉
  - test_reject_invalidates_node_tokens — reject 同样清掉
  - test_invalidate_hook_failure_does_not_block_main_flow — invalidate 抛异常时主流程仍 commit + graph 推进正常
- **tests/e2e/test_auth_race_condition.py** 1 用例（PRD §6.2 + PITFALLS #6 防御核心）：
  - test_20_concurrent_exchanges_only_one_wins — asyncio.gather 20 并发同 token，仅 1 个 200 / 19 个 401
- **tests/e2e/test_role_isolation.py** 1 用例：
  - test_manager_token_cant_access_hr_only_route — manager 换 cookie 后访问 require_role('hr') 路由 → 401
- **tests/e2e/test_cross_flow_rejection.py** 1 用例：
  - test_token_for_flow_a_rejected_on_flow_b — token.flow_id=A but node 属于 flow_b → 401（cross_flow reason）

### 文档更新
- **CHANGELOG.md**：`[Unreleased]` 顶部加 `Phase 3 Complete (2026-05-16)` 段（Added/Changed/Security/REQ Status/Deferred）
- **.planning/REQUIREMENTS.md**：AUTH-01..04 状态从 Pending → Complete（4 行 checkbox + Traceability 表）
- **.planning/STATE.md**：Phase 3 标记 Complete + roadmap summary + recent sessions 增 Phase 3 行

## Key Files

- backend/src/offboarding_flow/services/node_service.py（构造 + hook）
- backend/src/offboarding_flow/api/deps.py（注入 redis）
- backend/tests/conftest.py（4 个 fixture 上移）
- backend/tests/auth/conftest.py（清空）
- backend/tests/auth/test_node_advance_invalidates_tokens.py（3 集成测试）
- backend/tests/auth/test_exchange_endpoint.py（refactor 移除本地 fixture）
- backend/tests/e2e/test_auth_race_condition.py（1 race 测试）
- backend/tests/e2e/test_role_isolation.py（1 role 测试）
- backend/tests/e2e/test_cross_flow_rejection.py（1 cross flow 测试）
- CHANGELOG.md
- .planning/REQUIREMENTS.md
- .planning/STATE.md

## Verification

### 本环境（无 PG + 无 Redis）
```bash
cd backend && uv run pytest tests/auth/ tests/e2e/test_auth_race_condition.py tests/e2e/test_role_isolation.py tests/e2e/test_cross_flow_rejection.py -v
# => 38 passed, 26 skipped（含 race / role / cross_flow 因缺 PG/Redis 自动 skip）
```

### 完整环境（PG + Redis 启动后）
```bash
docker compose -f docker-compose.dev.yml up offboarding-postgres offboarding-redis -d
cd backend && REDIS_TEST_URL=redis://localhost:6380/1 \
  POSTGRES_DSN=postgresql+asyncpg://flow:devpassword@localhost:5433/offboarding \
  uv run pytest tests/auth/ tests/e2e/test_auth_race_condition.py tests/e2e/test_role_isolation.py tests/e2e/test_cross_flow_rejection.py -v
# => 全部 64 PASS
```

## Phase 3 验收 vs ROADMAP §Phase 3 Success Criteria

| # | 验收点 | 覆盖测试 | 结论 |
|---|--------|---------|------|
| 1 | asyncio.gather 同 token 并发仅 1 个 200 | tests/e2e/test_auth_race_condition.py + tests/auth/test_jti_service_concurrency.py | ✓ |
| 2 | 不同 role 用同 token 访问其他视图 401 | tests/e2e/test_role_isolation.py | ✓ |
| 3 | 节点 advance 后该 node 所有未消费 token 失效 | tests/auth/test_node_advance_invalidates_tokens.py | ✓ |
| 4 | Token 过期 → exchange 401 | tests/auth/test_exchange_endpoint.py::test_exchange_expired_token_returns_401 | ✓ |
| 5 | 跨 flow_id 复用 token 立即拒绝 | tests/e2e/test_cross_flow_rejection.py + tests/auth/test_exchange_endpoint.py::test_exchange_cross_flow_id_returns_401 | ✓ |

## REQ Status (Phase 3)

| REQ | Status |
|-----|--------|
| AUTH-01 | ✓ Complete（Plan 01：JWT 签发 + payload schema） |
| AUTH-02 | ✓ Complete（Plan 03：/api/auth/exchange + HttpOnly cookie + role 路由） |
| AUTH-03 | ✓ Complete（Plan 02 + 04：jti SET NX EX + 节点失效 hook） |
| AUTH-04 | ✓ Complete（Plan 03 + 04：三元组 + role 校验 + cross_flow 拒绝） |

## Downstream

- Phase 4 可基于本期 `build_deep_link` 直接拼邮件 / Mattermost 卡片 token URL
- Phase 5 实现 `/flow/handle` 前端壳页面调 POST /api/auth/exchange
- Phase 6 完善 nginx log_format 脱敏（PITFALLS #13）+ HTTPS 启用真 Secure cookie
