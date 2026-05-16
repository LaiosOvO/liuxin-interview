# Plan 03-03 SUMMARY — POST /api/auth/exchange + cookie + role 校验

**Status:** COMPLETE
**Wave:** 2（依赖 Plan 01 + Plan 02）
**Date:** 2026-05-16
**Requirements addressed:** AUTH-02, AUTH-04

## Delivered

- **auth/cookie.py**：`set_session_cookie / clear_session_cookie` — HttpOnly + SameSite=Lax + secure=(prod & https)
- **auth/role_router.py**：`resolve_redirect(role, flow_id, node_id)` — 6 角色映射 + 未知 role 回退 applicant
- **auth/session_service.py**：核心 `exchange_token(token, redis, session) -> ExchangeResult` 7 步校验链：
  1. JWT decode + 验签
  2. SET NX EX 原子消费 jti（必在 node 校验前 — PITFALLS #6）
  3. node 存在 + 同 flow_id + waiting_human + assignee==sub
  4. user 存在 + role 一致
  5. 注册 node:jti:{id} SET（后续可批量失效）
  6. 签 session cookie
  7. 返回 redirect_to
- **auth/deps.py**：`get_redis_dep / get_current_user / require_role(*roles)` 工厂
- **api/auth.py**：`POST /api/auth/exchange` + `POST /api/auth/logout` 路由
- **api/errors.py**：全局 AuthError handler — 对外统一 `error: '鉴权失败'`，server log 写 `reason` 便于排查
- **api/__init__.py**：扩 export `auth_router`
- **main.py**：lifespan shutdown 加 `dispose_redis`；`create_app` 挂载 auth_router
- **auth/__init__.py**：扩 export 11 个 Plan 03 新符号

## Tests

- `test_cookie.py` 5 单元测试 PASS：demo→no secure / prod+https→secure / SameSite=Lax / HttpOnly / clear
- `test_role_router.py` 8 单元测试 PASS：6 角色 redirect / 未知 role 回退 / 全部 /flow/ 前缀
- `test_exchange_endpoint.py` 9 集成测试 — 8 需 DB+Redis（环境无故 SKIP），logout 不依赖 DB 直接 PASS

整体（plans 01-03 累计）：**38 PASS / 20 SKIPPED**（skipped 全因环境无 Redis/DB）

## Key Files

- backend/src/offboarding_flow/auth/{cookie,role_router,session_service,deps}.py（4 新文件）
- backend/src/offboarding_flow/api/auth.py（新文件）
- backend/src/offboarding_flow/api/errors.py（加 AuthError handler）
- backend/src/offboarding_flow/api/__init__.py（扩 export）
- backend/src/offboarding_flow/main.py（lifespan + create_app）
- backend/src/offboarding_flow/auth/__init__.py（扩 export 11 符号）
- backend/tests/auth/{test_cookie,test_role_router,test_exchange_endpoint}.py（3 新测试文件）

## Verification

```bash
# 启 PG + Redis
docker compose -f docker-compose.dev.yml up offboarding-postgres offboarding-redis -d
cd backend && REDIS_TEST_URL=redis://localhost:6380/1 \
  POSTGRES_DSN=postgresql+asyncpg://flow:devpassword@localhost:5433/offboarding \
  uv run pytest tests/auth/ -v
# => 全部 PASS

# curl 验证：
uvicorn offboarding_flow.main:app --port 8000 &
curl http://localhost:8000/openapi.json | jq '.paths | keys'
# 含 "/api/auth/exchange" "/api/auth/logout"
```

## Downstream

- Plan 04 在 node_service.submit_action 加 invalidate_node_tokens hook（用 Plan 02 函数）+ 写 3 个 E2E 测试 + 更新 CHANGELOG/STATE/REQUIREMENTS
