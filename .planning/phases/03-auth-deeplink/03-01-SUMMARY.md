# Plan 03-01 SUMMARY — JWT 编解码 + 深链 + 异常体系

**Status:** COMPLETE
**Wave:** 1
**Date:** 2026-05-16
**Requirements addressed:** AUTH-01

## Delivered

- **依赖**：`pyjwt[crypto]>=2.10,<3` 已加 backend/pyproject.toml + uv.lock 更新
- **config.py**：新增 `session_expiry_hours / https_enabled / session_cookie_name`；生产模式 `JWT_SECRET` 启动校验（拒绝默认占位值）
- **.env.example**：Phase 3 段补全 `SESSION_EXPIRY_HOURS / HTTPS_ENABLED / SESSION_COOKIE_NAME`
- **auth/__init__.py**：公共 API export
- **auth/errors.py**：`AuthError / ExpiredTokenError / InvalidTokenError / TokenAlreadyConsumedError`（对外 401 统一 detail，内部 reason 供 log）
- **auth/schemas.py**：`JWTPayload`（PRD §6.2.1 锁定字段）+ `SessionPayload`（cookie 精简版，typ='session' 区分）；Pydantic v2 + extra='forbid'
- **auth/jwt_service.py**：`encode / decode / encode_session / decode_session` — HS256 + leeway=0 严格 exp 校验，pyjwt 异常映射到 AuthError 子类
- **auth/deep_link.py**：`build_deep_link(token, payload, *, base_url)` — query string 格式 `/flow/handle?flow_id=...&node_id=...&token=...`（R2 方案 A 锁定）

## Tests

- `tests/auth/factories.py`：`JWTPayloadFactory / SessionPayloadFactory`（polyfactory）
- **24 个单元测试 PASS**：
  - `test_schemas.py` 11 个：full fields ok / 6 个 missing field 抛 ValidationError / extra forbid / typ 默认 / jti 最小长度 / session extra forbid
  - `test_jwt_service.py` 8 个：encode→decode round trip / 过期 / 错 secret / 错算法 / 缺 claim / 畸形 token / schema 错 / encode_session round trip
  - `test_deep_link.py` 5 个：基础 / 去尾斜杠 / UUID 值正确 / path=/flow/handle / 三个 query key 齐全
- 覆盖率：jwt_service.py + deep_link.py + schemas.py + errors.py 均 ≥ 80%（实测 100%）

## Key Files

- backend/src/offboarding_flow/auth/{__init__,errors,schemas,jwt_service,deep_link}.py（5 个新文件）
- backend/src/offboarding_flow/config.py（扩展 3 字段 + prod 校验）
- backend/tests/auth/{__init__,factories,test_schemas,test_jwt_service,test_deep_link}.py（5 个新文件）
- .env.example（Phase 3 段）

## Verification

```bash
cd backend && uv run pytest tests/auth/test_schemas.py tests/auth/test_jwt_service.py tests/auth/test_deep_link.py -v
# => 24 passed
```

## Downstream

- Plan 02 可独立用 `JWTPayload` 类型签名（虽然 Plan 02 接口只用 str/UUID，但 schema 已就绪）
- Plan 03 直接 import `auth.jwt_service / auth.deep_link / auth.errors / auth.schemas`
