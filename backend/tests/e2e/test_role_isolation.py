"""E2E: 不同 role 用同 token 访问其他 role 视图 → 401（require_role 校验）。

验收 ROADMAP §Phase 3 Success Criteria #2
"""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, Depends

from offboarding_flow.auth import JWTPayload, encode
from offboarding_flow.auth.deps import require_role

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def app_with_protected_routes() -> AsyncGenerator[httpx.AsyncClient, None]:
    """加一个 require_role('hr') 的临时路由验证 role 校验。"""
    from offboarding_flow.main import create_app

    app = create_app()
    test_router = APIRouter()

    @test_router.get("/api/test/hr-only")
    async def hr_only(user=Depends(require_role("hr"))) -> dict:
        return {"role": user.role, "sub": user.sub}

    app.include_router(test_router)
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


async def test_manager_token_cant_access_hr_only_route(
    app_with_protected_routes: httpx.AsyncClient,
    sample_node_and_user,
    redis_client,
) -> None:
    """manager 换 cookie 后访问 hr-only 路由 → 401。"""
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

    # 1. exchange → 设 cookie
    ex_resp = await app_with_protected_routes.post("/api/auth/exchange", json={"token": token})
    assert ex_resp.status_code == 200

    # 2. 用 cookie 访问 hr-only → 401（cookie 自动随后续请求带上）
    hr_resp = await app_with_protected_routes.get("/api/test/hr-only")
    assert hr_resp.status_code == 401
    body = hr_resp.json()
    assert body["success"] is False
