"""POST /api/internal/huly/event 集成测试 — BRIDGE_TOKEN 鉴权 + listener 路由。

覆盖：
1. 缺 X-Bridge-Token → 401
2. 错 X-Bridge-Token → 401
3. 正确 token + listener 已注入 → 200 + handle_webhook 被调用
4. listener 未注入（IM_PROVIDER != huly）→ 503

注：本测试用 httpx.AsyncClient + 直接挂 router 的最小 FastAPI app（不起 lifespan），
聚焦验证路由 + 鉴权 + listener 转发逻辑。完整 lifespan 路径在 E2E 测试覆盖。
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from offboarding_flow.api.internal_huly import router as internal_huly_router


def _make_app(*, bridge_token: str = "test-bridge-token", listener=None) -> FastAPI:
    """构造最小 FastAPI app + 注入 settings + listener 到 app.state。"""
    app = FastAPI()
    app.include_router(internal_huly_router)
    app.state.huly_listener = listener
    return app


def _patch_settings(
    monkeypatch: pytest.MonkeyPatch, *, bridge_token: str = "test-bridge-token"
) -> None:
    """Patch get_settings 使其返回带指定 bridge_token 的 settings。"""
    from unittest.mock import MagicMock

    fake_settings = MagicMock()
    fake_settings.huly_bridge_token = bridge_token
    monkeypatch.setattr(
        "offboarding_flow.api.internal_huly.get_settings",
        lambda: fake_settings,
    )


# ───────── 1. 缺 X-Bridge-Token → 401 ─────────


@pytest.mark.asyncio
async def test_missing_bridge_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch)
    app = _make_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/api/internal/huly/event", json={"sender_account": "x"})

    assert r.status_code == 401
    assert r.json()["detail"] == "bridge_auth_failed"


# ───────── 2. 错 X-Bridge-Token → 401 ─────────


@pytest.mark.asyncio
async def test_wrong_bridge_token_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, bridge_token="real-token")
    app = _make_app()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/internal/huly/event",
            json={"sender_account": "x"},
            headers={"X-Bridge-Token": "wrong-token"},
        )

    assert r.status_code == 401
    assert r.json()["detail"] == "bridge_auth_failed"


# ───────── 3. 正确 token + listener 注入 → 200 + handle_webhook 调用 ─────────


@pytest.mark.asyncio
async def test_valid_token_invokes_listener_handle_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, bridge_token="valid-token")

    listener = AsyncMock()
    listener.handle_webhook = AsyncMock()
    app = _make_app(listener=listener)

    payload = {
        "sender_account": "uuid-zhang",
        "sender_username": "zhang.san",
        "channel_id": "dm-1",
        "channel_type": "D",
        "message": "我要离职",
        "ts": 1700000000000,
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/internal/huly/event",
            json=payload,
            headers={"X-Bridge-Token": "valid-token"},
        )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    listener.handle_webhook.assert_awaited_once_with(payload)


# ───────── 4. listener 未注入 → 503 ─────────


@pytest.mark.asyncio
async def test_listener_not_initialized_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_settings(monkeypatch, bridge_token="valid-token")
    app = _make_app(listener=None)  # 未注入

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/internal/huly/event",
            json={"sender_account": "x"},
            headers={"X-Bridge-Token": "valid-token"},
        )

    assert r.status_code == 503
    assert r.json()["detail"] == "huly_listener_not_initialized"


# ───────── 5. BRIDGE_TOKEN 配置为空 → 401（防意外开放） ─────────


@pytest.mark.asyncio
async def test_empty_bridge_token_config_rejects_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """运营误配 HULY_BRIDGE_TOKEN="" 时，任何请求都应被 401（防 open relay）。"""
    _patch_settings(monkeypatch, bridge_token="")

    listener = AsyncMock()
    listener.handle_webhook = AsyncMock()
    app = _make_app(listener=listener)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/api/internal/huly/event",
            json={"sender_account": "x"},
            headers={"X-Bridge-Token": ""},
        )

    assert r.status_code == 401
    listener.handle_webhook.assert_not_awaited()
