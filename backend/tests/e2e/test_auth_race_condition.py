"""E2E: PRD §6.2 + PITFALLS #6 — 双击 race condition。

验收 ROADMAP §Phase 3 Success Criteria #1:
    asyncio.gather(exchange(token), exchange(token)) 仅 1 个 200，其余 401

注：本测试用 ASGITransport 即可（不需 real container），故不带 e2e marker
（pytest 默认运行），方便 CI 直接覆盖该核心保证。
"""

from __future__ import annotations

import asyncio
import time
import uuid

import httpx
import pytest

from offboarding_flow.auth import JWTPayload, encode

pytestmark = pytest.mark.asyncio


async def test_20_concurrent_exchanges_only_one_wins(
    http_client: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """20 并发 exchange 同 token，仅 1 个 200 / 19 个 401（PITFALLS #6 防御核心）。"""
    payload = JWTPayload(
        sub=sample_node_and_user["user"].username,
        email="li.si@demo.local",
        role="manager",
        flow_id=sample_node_and_user["flow"].id,
        node_id=sample_node_and_user["node"].id,
        node_name="manager_review",
        allowed_actions=["advance", "return", "reject"],
        iat=int(time.time()),
        exp=int(time.time()) + 3600,
        jti=uuid.uuid4().hex,
    )
    token = encode(payload)

    async def call() -> httpx.Response:
        return await http_client.post("/api/auth/exchange", json={"token": token})

    responses = await asyncio.gather(*[call() for _ in range(20)])
    status_200 = sum(1 for r in responses if r.status_code == 200)
    status_401 = sum(1 for r in responses if r.status_code == 401)

    assert status_200 == 1, f"期望仅 1 个 200，实际 {status_200}"
    assert status_401 == 19, f"期望 19 个 401，实际 {status_401}"
