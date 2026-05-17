"""HulyIMProvider 单元测试 — 用 httpx.MockTransport 拦截 sidecar HTTP。

覆盖：
1. send_dm POST /api/im/send_dm 含 to_username/markdown + X-Bridge-Token header
2. post_to_channel POST /api/im/post_channel
3. ensure_user_in_channel POST /api/im/ensure_member
4. list_team_users 返回空列表（v1 stub）
5. resolve_username 返回 demo 域名 UserInfo
6. register_command_listener no-op（满足 Protocol）
7. send_dm 404 → ProviderError USER_NOT_FOUND
8. send_dm 500 → ProviderError
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from offboarding_flow.providers.base import IMProvider, ProviderError, UserInfo
from offboarding_flow.providers.huly_im_provider import HulyIMProvider


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.huly_bridge_url = "http://huly-bridge:7777"
    s.huly_bridge_token = "test-token-xxx"
    s.huly_bridge_http_timeout = 5.0
    return s


def _make_provider_with_transport(handler) -> HulyIMProvider:
    """构造 HulyIMProvider，注入 MockTransport（pytest fixtures 直接调用）。"""
    settings = _make_settings()
    provider = HulyIMProvider(settings)
    transport = httpx.MockTransport(handler)

    # monkey-patch _client 返回带 MockTransport 的 client
    def _patched_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.huly_bridge_url,
            headers={
                "Content-Type": "application/json",
                "X-Bridge-Token": settings.huly_bridge_token,
            },
            timeout=settings.huly_bridge_http_timeout,
            transport=transport,
        )

    provider._client = _patched_client  # type: ignore[method-assign]
    return provider


# ───────── 1. send_dm ─────────


@pytest.mark.asyncio
async def test_send_dm_posts_correct_payload_and_header() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        captured["token"] = request.headers.get("X-Bridge-Token")
        return httpx.Response(
            200, json={"ok": True, "data": {"message_id": "msg-1", "dm_id": "dm-1"}}
        )

    provider = _make_provider_with_transport(handler)
    await provider.send_dm("hr.alice", "你好")

    assert captured["url"].endswith("/api/im/send_dm")
    import json

    body = json.loads(captured["body"])
    assert body == {"to_username": "hr.alice", "markdown": "你好"}
    assert captured["token"] == "test-token-xxx"


# ───────── 2. post_to_channel ─────────


@pytest.mark.asyncio
async def test_post_to_channel_posts_correct_payload() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "data": {"message_id": "msg-2"}})

    provider = _make_provider_with_transport(handler)
    await provider.post_to_channel("channel-1", "**announcement**")

    assert captured["url"].endswith("/api/im/post_channel")
    import json

    body = json.loads(captured["body"])
    assert body == {"channel_id": "channel-1", "markdown": "**announcement**"}


# ───────── 3. ensure_user_in_channel ─────────


@pytest.mark.asyncio
async def test_ensure_user_in_channel_posts_correct_payload() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "data": {"already_member": False}})

    provider = _make_provider_with_transport(handler)
    await provider.ensure_user_in_channel("channel-1", "hr.alice")

    assert captured["url"].endswith("/api/im/ensure_member")
    import json

    body = json.loads(captured["body"])
    assert body == {"channel_id": "channel-1", "username": "hr.alice"}


# ───────── 4. list_team_users（v1 stub） ─────────


@pytest.mark.asyncio
async def test_list_team_users_returns_empty_list_v1(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    settings = _make_settings()
    provider = HulyIMProvider(settings)
    with caplog.at_level(logging.WARNING, logger="offboarding_flow.providers.huly_im_provider"):
        result = await provider.list_team_users()
    assert result == []
    assert any("list_team_users" in r.message for r in caplog.records)


# ───────── 5. resolve_username ─────────


@pytest.mark.asyncio
async def test_resolve_username_returns_demo_user_info() -> None:
    settings = _make_settings()
    provider = HulyIMProvider(settings)
    result = await provider.resolve_username("zhang.san")
    assert result is not None
    assert result.username == "zhang.san"
    assert result.email == "zhang.san@demo.local"
    assert result.provider == "huly"


@pytest.mark.asyncio
async def test_resolve_username_empty_returns_none() -> None:
    settings = _make_settings()
    provider = HulyIMProvider(settings)
    result = await provider.resolve_username("")
    assert result is None


# ───────── 6. register_command_listener no-op ─────────


def test_register_command_listener_is_noop_but_stores_dispatch() -> None:
    settings = _make_settings()
    provider = HulyIMProvider(settings)

    async def dummy_dispatch(**kwargs) -> None:
        pass

    provider.register_command_listener(dummy_dispatch)
    assert provider._dispatch is dummy_dispatch


# ───────── 7. send_dm 404 → ProviderError ─────────


@pytest.mark.asyncio
async def test_send_dm_user_not_found_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={
                "ok": False,
                "error": "未找到 username=ghost 对应的 Huly account",
                "code": "USER_NOT_FOUND",
            },
        )

    provider = _make_provider_with_transport(handler)
    with pytest.raises(ProviderError, match="USER_NOT_FOUND"):
        await provider.send_dm("ghost", "hi")


# ───────── 8. send_dm 500 → ProviderError ─────────


@pytest.mark.asyncio
async def test_send_dm_500_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False, "error": "boom", "code": "INTERNAL_ERROR"})

    provider = _make_provider_with_transport(handler)
    with pytest.raises(ProviderError, match="INTERNAL_ERROR"):
        await provider.send_dm("hr.alice", "hi")


# ───────── 9. Protocol 校验 ─────────


def test_huly_im_provider_satisfies_im_provider_protocol() -> None:
    """HulyIMProvider 必须满足 IMProvider Protocol（runtime_checkable）。"""
    settings = _make_settings()
    provider = HulyIMProvider(settings)
    assert isinstance(provider, IMProvider)
    assert provider.name == "huly"


# ───────── 10. UserInfo dataclass 校验 ─────────


@pytest.mark.asyncio
async def test_resolve_username_returns_userinfo_instance() -> None:
    settings = _make_settings()
    provider = HulyIMProvider(settings)
    result = await provider.resolve_username("hr.alice")
    assert isinstance(result, UserInfo)
