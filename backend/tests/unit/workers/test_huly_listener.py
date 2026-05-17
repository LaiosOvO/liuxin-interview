"""HulyListener 单元测试 — Protocol + handle_webhook 转发逻辑。

覆盖：
1. HulyListener 满足 IMListener Protocol（runtime_checkable）
2. handle_webhook 未注册 dispatch → log warning + 不抛
3. handle_webhook 已注册 → dispatch_message 被调用 + 参数正确
4. handle_webhook 空消息 → debug log + 不调 dispatch
5. handle_webhook sender_username 缺失 → 用 sender_account 兜底
6. name == "huly"
7. start / stop 是 no-op（webhook 模式）
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.im.protocol import IMListener
from offboarding_flow.workers.huly_listener import HulyListener


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.huly_bridge_url = "http://huly-bridge:7777"
    s.huly_bridge_token = "test-token-xxx"
    s.huly_bridge_http_timeout = 5.0
    s.im_provider = "huly"
    s.doc_provider = "huly"
    return s


# ───────── 1. Protocol 一致性 ─────────


def test_huly_listener_satisfies_im_listener_protocol() -> None:
    listener = HulyListener(_make_settings())
    assert isinstance(listener, IMListener)


# ───────── 2. name ─────────


def test_huly_listener_name_is_huly() -> None:
    listener = HulyListener(_make_settings())
    assert listener.name == "huly"


# ───────── 3. start / stop no-op ─────────


@pytest.mark.asyncio
async def test_start_and_stop_are_noop_log_only(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    listener = HulyListener(_make_settings())
    with caplog.at_level(logging.INFO, logger="offboarding_flow.workers.huly_listener"):
        await listener.start()
        await listener.stop()
    messages = " ".join(r.message for r in caplog.records)
    assert "启动" in messages or "webhook" in messages


# ───────── 4. handle_webhook 未注册 dispatch ─────────


@pytest.mark.asyncio
async def test_handle_webhook_without_dispatch_warns_and_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    listener = HulyListener(_make_settings())
    # 故意不 register

    with caplog.at_level(logging.WARNING, logger="offboarding_flow.workers.huly_listener"):
        await listener.handle_webhook(
            {
                "sender_account": "uuid-x",
                "sender_username": "hr.alice",
                "channel_id": "ch-1",
                "channel_type": "D",
                "message": "help",
                "ts": 1700000000000,
            }
        )

    assert any("dispatch 未注册" in r.message for r in caplog.records)


# ───────── 5. handle_webhook 已注册 dispatch ─────────


@pytest.mark.asyncio
async def test_handle_webhook_registered_dispatch_invoked_correctly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """handle_webhook → dispatch_message 被调用 + sender_username / channel_id / message 正确。"""
    listener = HulyListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    # mock provider factory（避免真起 httpx 客户端）
    fake_provider = MagicMock()
    fake_provider.post_to_channel = AsyncMock()
    fake_provider.send_dm = AsyncMock()
    fake_provider.ensure_user_in_channel = AsyncMock()
    monkeypatch.setattr(
        "offboarding_flow.providers.factory.get_im_provider",
        lambda: fake_provider,
    )

    await listener.handle_webhook(
        {
            "sender_account": "uuid-zhang",
            "sender_username": "zhang.san",
            "channel_id": "dm-1",
            "channel_type": "D",
            "message": "我要离职",
            "ts": 1700000000000,
        }
    )

    dispatch_mock.assert_awaited_once()
    call_kwargs = dispatch_mock.await_args.kwargs
    assert call_kwargs["sender_username"] == "zhang.san"
    assert call_kwargs["user_id"] == "uuid-zhang"
    assert call_kwargs["channel_id"] == "dm-1"
    assert call_kwargs["channel_type"] == "D"
    assert call_kwargs["message"] == "我要离职"
    # IMHelpers 必须含 post_channel / send_dm（来自 mocked provider）
    helpers = call_kwargs["im_helpers"]
    assert helpers.post_channel is fake_provider.post_to_channel
    assert helpers.send_dm is fake_provider.send_dm


# ───────── 6. handle_webhook 空消息 ─────────


@pytest.mark.asyncio
async def test_handle_webhook_empty_message_skips() -> None:
    listener = HulyListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    await listener.handle_webhook(
        {
            "sender_account": "uuid-x",
            "sender_username": "hr.alice",
            "channel_id": "ch-1",
            "channel_type": "D",
            "message": "   ",  # 空白
            "ts": 1700000000000,
        }
    )

    dispatch_mock.assert_not_awaited()


# ───────── 7. handle_webhook sender_username 缺失 ─────────


@pytest.mark.asyncio
async def test_handle_webhook_missing_sender_username_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = HulyListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    fake_provider = MagicMock()
    fake_provider.post_to_channel = AsyncMock()
    fake_provider.send_dm = AsyncMock()
    fake_provider.ensure_user_in_channel = AsyncMock()
    monkeypatch.setattr(
        "offboarding_flow.providers.factory.get_im_provider",
        lambda: fake_provider,
    )

    await listener.handle_webhook(
        {
            "sender_account": "uuid-zhang",
            "sender_username": None,  # 缺
            "channel_id": "dm-1",
            "channel_type": "D",
            "message": "help",
            "ts": 1700000000000,
        }
    )

    dispatch_mock.assert_awaited_once()
    call_kwargs = dispatch_mock.await_args.kwargs
    # 兜底用 sender_account 作为 sender_username
    assert call_kwargs["sender_username"] == "uuid-zhang"
