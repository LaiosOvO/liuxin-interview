"""POST /api/auth/exchange 集成测试 — 真 PG + 真 Redis（CLAUDE.md §2.3 禁 mock）。

约定：
- REDIS_TEST_URL=redis://localhost:6380/1
- POSTGRES_DSN=postgresql+asyncpg://flow:devpassword@localhost:5433/offboarding
- 启动：`docker compose -f docker-compose.dev.yml up offboarding-postgres offboarding-redis -d`
- DB/Redis 不可达时 pytest.skip（fixture 内）

覆盖 ROADMAP §Phase 3 Success Criteria #1 #2 #4 #5 + AUTH-02 + AUTH-04。
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.auth import JWTPayload, encode
from offboarding_flow.state_store.enums import NodeStatus

pytestmark = pytest.mark.asyncio


def _make_token(
    *,
    sub: str,
    role: str,
    flow_id: uuid.UUID,
    node_id: uuid.UUID,
    jti: str | None = None,
    exp_in: int = 3600,
    node_name: str = "manager_review",
) -> str:
    payload = JWTPayload(
        sub=sub,
        email=f"{sub}@demo.local",
        role=role,
        flow_id=flow_id,
        node_id=node_id,
        node_name=node_name,
        allowed_actions=["advance", "return", "reject"],
        iat=int(time.time()),
        exp=int(time.time()) + exp_in,
        jti=jti or uuid.uuid4().hex,
    )
    return encode(payload)


# ---------------------------------------------------------------------------
# 8 个端点用例
# ---------------------------------------------------------------------------


async def test_exchange_success_sets_cookie_and_returns_200(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """正常路径：200 + envelope.success=True + Set-Cookie。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["role"] == "manager"
    assert body["data"]["redirect_to"].startswith("/flow/")
    set_cookie_headers = [
        v.decode() if isinstance(v, bytes) else v
        for k, v in resp.headers.raw
        if k.lower() == b"set-cookie"
    ]
    assert any("offboarding_session" in sc for sc in set_cookie_headers), set_cookie_headers


async def test_exchange_jti_replay_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """同 token 第二次 exchange → 401（PITFALLS #6 防双击 race 验证）。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    r1 = await http_client.post("/api/auth/exchange", json={"token": token})
    r2 = await http_client.post("/api/auth/exchange", json={"token": token})
    assert r1.status_code == 200
    assert r2.status_code == 401


async def test_exchange_expired_token_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """过期 token → 401（ROADMAP §SC #4）。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
        exp_in=-60,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401


async def test_exchange_cross_flow_id_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """跨 flow_id（payload.flow_id 与 node.flow_id 不一致）→ 401（ROADMAP §SC #5）。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=uuid.uuid4(),  # 错的 flow_id
        node_id=sample_node_and_user["node"].id,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401


async def test_exchange_role_mismatch_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """payload.role 与 user.role 不一致 → 401。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="hr",  # 错的 role（user 是 manager）
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401


async def test_exchange_sub_mismatch_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """payload.sub 与 node.assignee 不一致 → 401（AUTH-04 三元组绑定）。"""
    token = _make_token(
        sub="wang.wu",  # 错的 sub（node assignee 是 li.si_xxx）
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401


async def test_exchange_node_already_done_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
    db_session: AsyncSession,
) -> None:
    """节点已 done → 401。"""
    # 把 node 改成 done
    sample_node_and_user["node"].status = NodeStatus.DONE.value
    await db_session.commit()
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401


async def test_exchange_tampered_signature_returns_401(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """签名被篡改 → 401。"""
    token = _make_token(
        sub=sample_node_and_user["user"].username,
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
    )
    # 改最后字符破坏签名
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    resp = await http_client.post("/api/auth/exchange", json={"token": tampered})
    assert resp.status_code == 401


async def test_logout_clears_cookie(http_client: httpx.AsyncClient) -> None:
    """POST /api/auth/logout 返回 200 + 清 cookie。"""
    resp = await http_client.post("/api/auth/logout")
    assert resp.status_code == 200
    set_cookie_headers = [
        v.decode() if isinstance(v, bytes) else v
        for k, v in resp.headers.raw
        if k.lower() == b"set-cookie"
    ]
    assert any("offboarding_session" in sc for sc in set_cookie_headers)
