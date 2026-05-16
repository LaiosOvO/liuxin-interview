# Phase 3: 鉴权 + 深链 JWT 一键登录 + jti 一次性消费 - Context

**Gathered:** 2026-05-16
**Status:** Ready for planning
**Mode:** `--auto`（context 全部来自既有文档，无需 4 问深挖；本文档仅作 planner 的入口索引）

---

<domain>
## Phase Boundary

**交付目标**：在 Phase 1 跑通的最小骨架上，落地**邮件链接点击即登录**的核心机制。本期不依赖通知发送（Phase 4），不依赖前端页面（Phase 5），只交付后端鉴权 + 深链构造 + 一次性 token 消费 + role 校验 + 三元组绑定。

**必须交付（来自 ROADMAP.md §Phase 3 + REQUIREMENTS AUTH-01..04）：**

1. **JWT 签发 / 解码**（pyjwt[crypto] HS256，**不用 python-jose**，已 deprecated — SUMMARY R3）
   - payload schema：`sub / email / role / flow_id / node_id / node_name / allowed_actions / iat / exp / jti`
   - HS256 + JWT_SECRET（仅 env 注入，不入 git）
   - `build_deep_link()` helper — **方案 A query string**：`/flow/handle?flow_id=xxx&node_id=yyy&token=zzz`（PRD §6.2 + SUMMARY R2 必采）
2. **Redis jti 黑名单服务**
   - `SET key value NX EX ttl` 原子消费（PITFALLS #6 防双击 race）
   - 维护 `node:jti:{node_id}` SET，节点 advance/reject/return 后 SDEL 全部 token
   - aioredis（项目依赖 `redis>=5.2,<7` 内含 asyncio client）
3. **`POST /api/auth/exchange`** 端点
   - body: `{ token: str }`
   - 校验链：JWT 签名 / exp / jti 未消费 / (flow_id, node_id) 仍 waiting_human / sub 与 node.assignee 匹配 / role 与 node 配置匹配
   - 校验通过 → SET NX EX 消费 jti → 加入 node:jti:{id} SET → 签 HttpOnly Cookie → 返回 `{ redirect_to, role, name }`
   - 失败统一 401（拒绝信息泄露）
4. **Session Cookie 签发**
   - HttpOnly + `SameSite=Lax`（**不能 Strict** — PITFALLS #12，邮件链接跨站跳失效）
   - `secure=(APP_MODE=="prod" and HTTPS_ENABLED)`（内网 HTTP 不能开 Secure）
   - cookie 值 = 短 JWT（仅 sub/role/flow_id/exp，与 access token 不同的 secret 或不同 typ）
   - TTL 默认 24h（`SESSION_EXPIRY_HOURS`，独立于 token TTL）
5. **`get_current_user` FastAPI Depends**
   - 从 cookie 解码 → 返回 `AuthenticatedUser(sub, role, flow_id, exp)`
   - 失败抛 401
   - `require_role(*roles)` Depends 工厂封装角色断言
6. **节点状态变更 hook**
   - `node_service.submit_action` 在双写成功后调 `auth_jti_service.invalidate_node_tokens(node_id)`
   - 实现：SMEMBERS `node:jti:{id}` → DEL 每个 `jti:{value}` → DEL `node:jti:{id}`
   - 失败仅 log warning（不影响主链路）

**不交付（明确推到对应 phase）**：
- 通知里把 token 拼进邮件正文 → Phase 4
- 前端 `/flow/handle` 静态壳页面 → Phase 5
- nginx `log_format` 不记录 query 防 token 泄露 → Phase 6（PITFALLS #13）
- HTTPS 启用 + 真 secure cookie → Phase 6
- 角色 → 视图 path 映射的前端实现 → Phase 5
- Mattermost Outgoing Webhook callback 签名 → Phase 4

**Phase 3 验收（ROADMAP §Phase 3 Success Criteria）**：

1. `asyncio.gather(exchange(token), exchange(token))` 并发同一 token **只有一个返回 200**，另一个 401
2. 不同 role 用同一 token 访问其他 role 视图：立即 401
3. 节点状态 advance/reject/return 后，该 node 所有未消费 token 立即失效（再 exchange 返回 401）
4. Token 过期后 exchange 返回 401（exp 严格校验）
5. 跨 flow_id 复用 token 立即拒绝（payload 的 flow_id 与 URL 的 flow_id 不一致）

</domain>

---

<decisions>
## Implementation Decisions

> 全部锁定决策已在 CLAUDE.md / PRD.md / SUMMARY.md / PITFALLS.md / 01-CONTEXT.md 中明确，本节仅汇总要点便于 planner 快速对齐。

### D1. 技术栈（继承 Phase 1 + 新增）

- Python 3.12+ / uv / FastAPI（已在 backend/pyproject.toml）
- 新增 dep：`pyjwt[crypto]>=2.10,<3`（HS256 + 未来扩展 RS256）
- 复用现有：`redis>=5.2,<7`（含 `redis.asyncio.Redis` client）— Phase 1 已在依赖里但 graph/health 仅占位
- 测试：`pytest-asyncio` + `polyfactory` + `httpx.AsyncClient` + `asgi-lifespan`
- 集成测试**禁止 mock Redis**（用户 memory `feedback_e2e_browser_harness` + CLAUDE.md §2.3）— 用真 `offboarding-redis` 测试 DB 0/1 切换 或者 fakeredis 也不允许；测试在 conftest 起独立 redis container client

### D2. 模块划分（新增 `auth/` 包）

```
backend/src/offboarding_flow/
└── auth/                            # 本 phase 新增
    ├── __init__.py                  # export 公共 API
    ├── jwt_service.py               # encode / decode + payload Pydantic schema
    ├── deep_link.py                 # build_deep_link() helper
    ├── jti_service.py               # Redis SET NX EX + node:jti:{id} SET 管理
    ├── cookie.py                    # set/clear session cookie helper
    ├── session_service.py           # exchange_token + session 签发 + role 校验
    └── deps.py                      # FastAPI Depends: get_current_user / require_role
```

```
backend/src/offboarding_flow/api/
├── auth.py                          # 本 phase 新增 — POST /api/auth/exchange
└── deps.py                          # 本 phase 扩展 — 加 get_redis_client / get_auth_service
```

### D3. 配置扩展（config.py）

新增字段（继承现有 `Settings` BaseSettings）：

```python
# JWT（已占位，本 phase 真启用）
jwt_secret: str = Field(default="changeme_in_real_env", validate_default=False)
token_expiry_hours: int = 24

# 新增：session cookie 独立 TTL（与 token TTL 解耦）
session_expiry_hours: int = 24

# 新增：HTTPS 启用开关（内网 HTTP 默认 False）
https_enabled: bool = False

# 新增：cookie 名（避免硬编码）
session_cookie_name: str = "offboarding_session"
```

启动时校验：`if app_mode == "prod" and jwt_secret == "changeme_in_real_env": raise RuntimeError("生产模式必须设置 JWT_SECRET")`

### D4. JWT Payload Schema（Pydantic v2）

```python
from pydantic import BaseModel, Field
from uuid import UUID

class JWTPayload(BaseModel):
    """deep-link token payload — PRD §6.2.1 锁定。"""
    sub: str                        # 操作人 username
    email: str
    role: str                       # employee / manager / hr / it_admin / finance / legal
    flow_id: UUID
    node_id: UUID
    node_name: str
    allowed_actions: list[str]      # ["advance", "return", "reject"] subset
    iat: int                        # unix ts
    exp: int                        # unix ts
    jti: str                        # uuid4 hex — 一次性
```

session cookie payload：

```python
class SessionPayload(BaseModel):
    """session cookie payload — 比 token 更精简。"""
    sub: str
    role: str
    flow_id: UUID
    node_id: UUID
    exp: int
    typ: str = "session"            # 区分 token vs session
```

### D5. Redis Key 约定

| Key | 类型 | TTL | 用途 |
|---|---|---|---|
| `jti:{jti_value}` | string ("consumed") | token TTL | 一次性消费标记 — SET NX EX |
| `node:jti:{node_id}` | SET of jti hex | token TTL | 节点未消费 token 集合 — 节点变更时批量失效 |

`SET NX EX` 用 `redis.set(key, value, nx=True, ex=ttl_seconds)`。

### D6. 深链 URL 格式（R2 方案 A 锁定）

`{DEEPLINK_BASE_URL}/flow/handle?flow_id={uuid}&node_id={uuid}&token={jwt}`

例：`http://192.168.2.44:3000/flow/handle?flow_id=8f3a...&node_id=a91c...&token=eyJhbGc...`

`build_deep_link(token: str, payload: JWTPayload, *, base_url: str) -> str`：
- 用 `urllib.parse.urlencode` 拼 query
- 不做 URL fragment（fragment 不发服务器）
- 不 base64 编码 token（破坏可读性，且 jwt 本身已 URL-safe base64）

### D7. cookie 签发约束（PITFALLS #12 锁定）

```python
def set_session_cookie(response, session_token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=(settings.app_mode == "prod" and settings.https_enabled),
        samesite="lax",        # 不能 strict — 邮件跳算 cross-site GET
        max_age=settings.session_expiry_hours * 3600,
        path="/",
    )
```

### D8. exchange_token 7 步校验链（PRD §6.2.2）

```python
async def exchange_token(token: str, redis: Redis, session: AsyncSession) -> ExchangeResult:
    # 1. JWT decode + 验签 + exp 校验（pyjwt 内置）
    payload = jwt_service.decode(token)           # 失败 → 401
    # 2. SET NX EX 消费 jti（原子）
    ok = await jti_service.consume(redis, payload.jti, ttl=...)
    if not ok:
        raise AuthError(401, "token 已使用或失效")
    # 3. node 仍 waiting_human + assignee == sub
    node = await node_repo.get(payload.node_id)
    if node is None or str(node.flow_id) != str(payload.flow_id):
        raise AuthError(401)                     # 跨 flow_id 立即拒绝
    if node.status != NodeStatus.WAITING_HUMAN:
        raise AuthError(401, "节点状态已变更")
    if node.assignee != payload.sub:
        raise AuthError(401, "用户与节点不匹配")
    # 4. user 仍存在 + role 一致
    user = await user_repo.get_by_username(payload.sub)
    if user is None or user.role.value != payload.role:
        raise AuthError(401, "用户角色已变更")
    # 5. 加入 node:jti:{id} SET 便于后续失效（必须在 consume 之后）
    await jti_service.register_node_token(redis, payload.node_id, payload.jti, ttl=...)
    # 6. 签 session cookie payload
    session_token = jwt_service.encode_session(payload)
    # 7. 返回 redirect_to（按 role 路由）
    redirect_to = role_router.resolve(payload.role, payload.flow_id, payload.node_id)
    return ExchangeResult(session_token=session_token, redirect_to=redirect_to,
                          role=payload.role, name=user.display_name)
```

**所有 401 错误都用统一 message 不暴露具体失败原因**（仅 log 详情）。

### D9. role → redirect_to 映射（最小集，Phase 5 完善）

```python
ROLE_REDIRECTS = {
    "applicant": "/flow/{flow_id}/applicant",
    "manager": "/flow/{flow_id}/node/{node_id}/manager",
    "hr": "/flow/{flow_id}/node/{node_id}/hr",
    "it_admin": "/flow/{flow_id}/node/{node_id}/it",
    "finance": "/flow/{flow_id}/node/{node_id}/finance",
    "legal": "/flow/{flow_id}/node/{node_id}/legal",
}
```

Phase 3 仅返回 URL 字符串，Phase 5 落地前端路由对应。

### D10. 节点状态变更失效 hook（node_service 扩展）

`node_service.submit_action` 在 `session.commit()` 之后、`graph.ainvoke` 之前，调：

```python
try:
    await self.jti_service.invalidate_node_tokens(self.redis, node_id)
    logger.info("[node_service] invalidated tokens for node=%s", node_id)
except Exception as e:
    logger.warning("[node_service] invalidate tokens failed (non-fatal): %s", e)
```

失败不阻断主链路（token 还会自然过期，只是窗口期 24h 内可被复用但已通过 jti 消费校验拦截）。

### D11. 测试三层（CLAUDE.md §2.1 + §2.3）

**Unit（无 Redis / 无 DB）**：
- `tests/auth/test_jwt_service.py` — encode → decode round trip / 过期 / 签名错 / sig 算法不匹配
- `tests/auth/test_deep_link.py` — build_deep_link query string 拼接 / URL-safe / 特殊字符
- `tests/auth/test_cookie.py` — set_session_cookie samesite/httponly/secure 按 app_mode 切换
- `tests/auth/test_role_router.py` — role redirect 映射

**Integration（真 Redis + 真 PG test schema）**：
- `tests/auth/test_jti_service_integration.py` — SET NX EX 原子性 / SMEMBERS / DEL / 过期回收
- `tests/auth/test_exchange_endpoint.py` — POST /api/auth/exchange 全 7 步校验链
  - 正常 200
  - jti 重放 → 401
  - 过期 token → 401
  - 跨 flow_id 复用 → 401
  - 跨 role 复用 → 401
  - node 已 done → 401
- `tests/auth/test_node_advance_invalidates_tokens.py` — node_service.submit_action 后 token 失效

**E2E（asyncio.gather 模拟双击 race）**：
- `tests/e2e/test_auth_race_condition.py` — `asyncio.gather(exchange, exchange, exchange)` 三并发 → 仅 1 个 200，2 个 401
- `tests/e2e/test_role_isolation.py` — manager token 不能给 hr 用
- `tests/e2e/test_cross_flow_rejection.py` — flow_a 的 token 不能消费 flow_b 的 node
- 标记 `@pytest.mark.e2e`（需真容器，默认 skip）

**覆盖率**：≥ 80%（CLAUDE.md 继承全局门槛）

### D12. 错误处理 + 日志

- 业务错误：`AuthError(status_code, detail, *, log_message)` 自定义异常 → exception handler 统一返回 envelope `{success:False, error:"鉴权失败"}` 隐藏细节，server log 写完整 detail
- structlog `event="auth.exchange.fail"` + `reason="jti_replay" / "expired" / "cross_flow"` 等结构化日志便于 ELK / grep
- 不写敏感字段（token 全文 / payload sub email）到 log，只写 jti 前缀 8 位 + node_id 前缀

### D13. Claude's Discretion（不需要回头问用户）

- `AuthError` 类与 FastAPI exception handler 注册细节
- pyjwt 的 leeway 参数（建议 0，严格 exp 校验）
- session cookie 签发是否复用 JWT_SECRET（推荐复用 + typ 字段区分；轻量方案）
- `node:jti:{id}` SET 的 TTL（取 token TTL，过期自然回收）
- `redis.asyncio.Redis` 连接池大小（默认 max_connections=10）
- exchange endpoint 是否 rate limit（Phase 3 不做，Phase 6 接 slowapi）
- 测试用 Redis DB 隔离（生产 DB=0，测试 DB=1）
- `polyfactory` factory 类是否单独文件（推荐 tests/auth/factories.py）
- 是否提供 `POST /api/auth/logout` 清 cookie 端点（推荐做，Phase 3 顺手 + 单元测试覆盖）

</decisions>

---

<specifics>
## Specific References

- **PRD §6.2 完整流程图 + 5 安全约束 + 6 角色视图表**（70-80 行原文）—— 本 phase 鉴权链路源头
- **PITFALLS #6 (JWT 双击 race) / #12 (Secure flag) / #13 (token in URL log)** —— 三个 P3 必看 pitfall
- **SUMMARY §5 R2 R8** —— R2 深链 URL 方案 A 锁定；R8 jti 必采 Redis SET NX EX
- **CLAUDE.md §1.1**（并行开发触发点）+ **§2.1/2.3**（全流程测试 + browser-harness）+ **§3.5**（凭证安全 — JWT_SECRET 永不入库）
- **01-CONTEXT.md §6 §11**（API envelope 模式 + 环境变量约定）
- **REQUIREMENTS.md AUTH-01..04**（4 条 v1 REQ，本 phase 必须全部 Pending → Complete）

## 用户原话回顾（来自 prompt）

- "鉴权 + 深链 JWT 一键登录 + jti 一次性消费" 是 Phase 3 主线
- "Redis SET NX EX 原子操作" 是核心并发安全保证
- "HttpOnly + SameSite=Lax 不能 Strict"
- "深链 URL = query string 格式，不是 path param"
- "跨节点/跨角色 token 立即拒绝"
- "集成测试用真 Redis + 真 PG test schema，不 mock"
- "JWT_SECRET 永远不写入任何 git tracked 文件"

## 推荐 Plan 拆分（4 个 plan，2-3 wave）

> 由 gsd-planner 最终确定，本节仅作建议

- **Plan 01**（Wave 1）：pyjwt 依赖 + JWT payload schema + jwt_service.encode/decode + deep_link.build + unit tests（无 Redis 依赖，可独立）
- **Plan 02**（Wave 1）：Redis client wiring + jti_service（SET NX EX + node:jti:{id} SET） + integration tests（依赖 plan 01 的 payload schema 但接口可先 stub）
- **Plan 03**（Wave 2）：cookie 模块 + session_service + auth/deps + POST /api/auth/exchange 端点 + 集成测试（依赖 plan 01 + 02）
- **Plan 04**（Wave 3）：node_service hook 集成 + E2E race condition / role isolation / cross-flow rejection 测试 + CHANGELOG + .env.example 更新 + config 校验

Wave 1 两个 plan 完全独立可并行（plan 02 用 stub payload）；Wave 2 等 Wave 1；Wave 3 等 Wave 2。

</specifics>

---

<deferred>
## Deferred to Future Phases

- 把 token 拼进邮件 / Mattermost 卡片 → Phase 4（NOTI-01/02）
- 前端 `/flow/handle` 页面 → Phase 5（WEB-02）
- nginx `log_format` query 脱敏 → Phase 6（PITFALLS #13）
- HTTPS 启用 + cookie `secure=True` 生效 → Phase 6
- token 撤销列表（refresh token / logout all sessions）→ v2
- SSO 替代演示用一键登录 → v2（REQUIREMENTS PROD-01）
- Mattermost Interactive Message callback 签名校验 → Phase 4（BOT-01）
- API rate limiting（slowapi）→ Phase 6
- JWT_SECRET 轮换机制 → v2

</deferred>

---

*Phase: 03-auth-deeplink*
*Context source: PRD v0.4 §6.2 + CLAUDE.md + SUMMARY R2/R8 + PITFALLS #6/#12/#13 + REQUIREMENTS AUTH-01..04 + 01-CONTEXT.md（无需 discuss-phase，HIGH confidence 可直接 plan）*
