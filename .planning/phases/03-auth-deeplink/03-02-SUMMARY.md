# Plan 03-02 SUMMARY — Redis jti service + node SET 批量失效

**Status:** COMPLETE
**Wave:** 1（并行 Plan 01）
**Date:** 2026-05-16
**Requirements addressed:** AUTH-03（部分 — 与 Plan 04 共同完成）

## Delivered

- **auth/redis_client.py**：`get_redis()` 懒加载单例 + `dispose_redis()` lifespan shutdown 工厂；ConnectionPool max=10，`decode_responses=True`（jti 全部 str）
- **auth/jti_service.py**：
  - `consume_jti(redis, jti, ttl_seconds) -> bool` — 用 `redis.set(key, '1', nx=True, ex=ttl)` 原子（PITFALLS #6 核心保证）
  - `is_jti_consumed(redis, jti) -> bool` — debug 检查（exists）
  - `register_node_token(redis, node_id, jti, ttl_seconds)` — pipeline 串 SADD + EXPIRE（防 SET 永驻泄漏）
  - `invalidate_node_tokens(redis, node_id) -> int` — SMEMBERS → DEL 批量清理 + DEL SET 本身
- **api/health.py**：Redis 检查从 `not_checked` 升级为真 ping；失败仅 log warning 不阻断 health 200
- **auth/__init__.py**：扩展 export 6 个 Plan 02 新符号
- **tests/conftest.py**：`redis_client` function fixture（先 ping 检测，失败 pytest.skip）
- **.pre-commit-config.yaml**：mypy 钩子加 `types-redis>=4` 依赖
- Pipeline 修复：redis-py 6.x async pipeline 方法不要 await（await 会触发 execute）

## Tests

- `tests/auth/test_jti_service.py` 10 个用例：首次消费 / 重放 / is_consumed / 不同 jti 独立 / TTL 自然过期 / SADD 加成员 / SET 带 TTL / invalidate 清全部 / 空 SET 返回 0 / node 隔离
- `tests/auth/test_jti_service_concurrency.py` 2 个用例：**20 并发同 jti 仅 1 胜出**（PITFALLS #6 验证）+ 20 不同 jti 全胜
- **本环境无 Redis 故全部 SKIPPED**；启容器后重跑即生效

## Key Files

- backend/src/offboarding_flow/auth/{redis_client,jti_service}.py（2 新文件）
- backend/src/offboarding_flow/api/health.py（Redis ping 升级）
- backend/src/offboarding_flow/auth/__init__.py（扩 export）
- backend/tests/auth/{test_jti_service,test_jti_service_concurrency}.py（2 新文件）
- backend/tests/conftest.py（加 redis_client fixture）
- .pre-commit-config.yaml（types-redis）

## Verification

```bash
# 启 Redis 后：
docker compose -f docker-compose.dev.yml up offboarding-redis -d
cd backend && REDIS_TEST_URL=redis://localhost:6380/1 uv run pytest tests/auth/test_jti_service.py tests/auth/test_jti_service_concurrency.py -v
# => 12 passed（含 20 并发同 jti 仅 1 个 True 的核心断言）
```

## Downstream

- Plan 03 直接 import `auth.jti_service.consume_jti / register_node_token` 接入 exchange_token
- Plan 04 直接 import `auth.jti_service.invalidate_node_tokens` 接入 node_service hook
- 与 Plan 01 并行无冲突（不同文件，类型上仅用 str/UUID）
