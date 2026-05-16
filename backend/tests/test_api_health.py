"""GET /api/health 集成测试 — 用 asgi-lifespan + httpx.AsyncClient。

不依赖真数据库 — DB 不通时 /api/health 仍应返回 200（status='degraded'）。
"""

from __future__ import annotations

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from offboarding_flow.main import create_app


@pytest.fixture
async def client():
    app = create_app()
    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


async def test_health_endpoint_returns_200(client):
    """health 端点必须始终返回 200（不论 DB 是否通）。"""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert "status" in body["data"]
    assert body["data"]["status"] in ("ok", "degraded")


async def test_health_envelope_shape(client):
    """响应必须是 {success, data, error, meta} envelope。"""
    resp = await client.get("/api/health")
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "error", "meta"}
    assert body["success"] is True
    assert body["error"] is None


async def test_health_reports_app_mode_version_components(client):
    """data 含 app_mode + version + components。"""
    resp = await client.get("/api/health")
    data = resp.json()["data"]
    assert "app_mode" in data
    assert data["app_mode"] in ("demo", "prod")
    assert "version" in data
    assert "components" in data
    assert "db" in data["components"]
    assert "graph" in data["components"]
    assert "redis" in data["components"]


async def test_404_returns_envelope(client):
    """未注册路由 404 仍走全局 exception handler 返回 envelope。"""
    resp = await client.get("/api/nonexistent")
    assert resp.status_code == 404
    body = resp.json()
    assert isinstance(body, dict)
    # Starlette 404 走我们注册的 HTTPException handler → envelope
    assert "success" in body
    assert body["success"] is False


async def test_method_not_allowed_returns_envelope(client):
    """GET-only 路由 POST → 405 走 HTTPException handler → envelope。"""
    resp = await client.post("/api/health", json={})
    assert resp.status_code == 405
    body = resp.json()
    assert body["success"] is False
    assert body["error"] is not None
