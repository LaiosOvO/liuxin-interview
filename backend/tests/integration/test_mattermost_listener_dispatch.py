"""MattermostListener ↔ IMListener Protocol 集成测试（ABS-01 / ABS-02 / ABS-04）。

覆盖 4 个用例：
1. MattermostListener 满足 IMListener Protocol（runtime_checkable）
2. 未 register_command_listener 时收到 WS 事件 → log warning + 不抛
3. register_command_listener 后 → _handle_event(fake WS event) → dispatch 被调用，
   参数正确（sender_username / channel_id / channel_type / message）
4. MattermostListener.name == "mattermost"

约定（CLAUDE.md §2.3）：
- 集成测试通常禁 mock DB；但本测试聚焦"listener ↔ dispatch 注入" 契约层面，
  dispatch 是注入点，单测中用 AsyncMock 替代 dispatch_message 本身（替的不是 DB）。
- Task 2 已用真 dispatch_message + mock 业务依赖覆盖；Task 3 集成测试只看
  "listener 是否正确把 WS 事件转化为 dispatch 调用"。
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.im.protocol import IMListener
from offboarding_flow.workers.mattermost_listener import MattermostListener


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.mattermost_url = "http://mm:8065"
    s.mattermost_bot_token = "fake-bot-token-xxxx"
    s.mattermost_bot_username = "offboarding-bot"
    s.mattermost_bot_user_id = "bot_user_id_abc"
    s.mattermost_team = "laios"
    return s


def _make_ws_event(
    *,
    sender_name: str = "hr.alice",
    sender_id: str = "user_alice_id",
    channel_id: str = "channel_dm_id",
    channel_type: str = "D",
    message: str = "help",
) -> str:
    """构造一个 mattermost websocket "posted" 事件 JSON（与真实 WS 帧同 schema）。"""
    post = {
        "user_id": sender_id,
        "channel_id": channel_id,
        "message": message,
    }
    event = {
        "event": "posted",
        "data": {
            "post": json.dumps(post),
            "channel_type": channel_type,
            "sender_name": "@" + sender_name,  # MM 真实 payload 带 @
        },
    }
    return json.dumps(event)


# ───────── 测试 1：Protocol 一致性 ─────────


def test_mattermost_listener_satisfies_im_listener_protocol() -> None:
    """ABS-01 — MattermostListener 必须满足 IMListener Protocol。"""
    listener = MattermostListener(_make_settings())
    assert isinstance(
        listener, IMListener
    ), "MattermostListener 必须满足 IMListener Protocol（含 name / start / stop / register_command_listener）"


# ───────── 测试 2：未 register 时丢弃 + log warning ─────────


@pytest.mark.asyncio
async def test_handle_event_without_dispatch_logs_warning_and_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ABS-04 — listener 未注册 dispatch 时收到事件 → 不抛 + log warning。"""
    listener = MattermostListener(_make_settings())
    # 故意不调 listener.register_command_listener(...)

    import logging

    with caplog.at_level(logging.WARNING, logger="offboarding_flow.workers.mattermost_listener"):
        await listener._handle_event(
            _make_ws_event(message="help", channel_type="D", sender_name="hr.alice")
        )

    # 必须 log warning（包含 "dispatch 未注册"）
    assert any(
        "dispatch 未注册" in r.message for r in caplog.records
    ), f"应记录 'dispatch 未注册' warning，实际 records: {[r.message for r in caplog.records]}"


# ───────── 测试 3：register 后 dispatch 被正确调用 ─────────


@pytest.mark.asyncio
async def test_handle_event_with_registered_dispatch_invokes_with_correct_args() -> None:
    """ABS-02 / ABS-04 — register 后 listener 应把 WS 事件正确转换为 dispatch 调用。"""
    listener = MattermostListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    await listener._handle_event(
        _make_ws_event(
            sender_name="hr.alice",
            sender_id="user_alice_id",
            channel_id="ch_dm",
            channel_type="D",
            message="help",
        )
    )

    dispatch_mock.assert_awaited_once()
    call_kwargs = dispatch_mock.call_args.kwargs
    assert call_kwargs["sender_username"] == "hr.alice"
    assert call_kwargs["user_id"] == "user_alice_id"
    assert call_kwargs["channel_id"] == "ch_dm"
    assert call_kwargs["channel_type"] == "D"
    assert call_kwargs["message"] == "help"
    # im_helpers 字段必须是 IMHelpers 实例
    from offboarding_flow.im.context import IMHelpers

    assert isinstance(call_kwargs["im_helpers"], IMHelpers)
    # 设置 + session_factory 字段非 None
    assert call_kwargs["settings"] is not None
    assert call_kwargs["session_factory"] is not None


@pytest.mark.asyncio
async def test_handle_event_skips_bot_self_post() -> None:
    """幂等性 — bot 自己发的消息（user_id == bot_user_id）必须 skip 不触发 dispatch。"""
    listener = MattermostListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    # bot 自身发的消息
    event = _make_ws_event(
        sender_name="offboarding-bot",
        sender_id="bot_user_id_abc",  # 与 settings.mattermost_bot_user_id 相同
        channel_id="ch",
        channel_type="D",
        message="自言自语",
    )
    await listener._handle_event(event)

    dispatch_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_event_skips_non_dm_without_mention_or_trigger() -> None:
    """触发条件 — channel 消息既无 @mention 也无关键词时不触发。"""
    listener = MattermostListener(_make_settings())
    dispatch_mock = AsyncMock()
    listener.register_command_listener(dispatch_mock)

    event = _make_ws_event(
        sender_name="hr.alice",
        sender_id="user_alice_id",
        channel_id="ch_public",
        channel_type="O",  # 公开频道
        message="今天午饭吃什么",  # 既无 @offboarding-bot 也无离职关键词
    )
    await listener._handle_event(event)

    dispatch_mock.assert_not_awaited()


# ───────── 测试 4：name 属性 ─────────


def test_mattermost_listener_name_equals_mattermost() -> None:
    """name 属性必须等于 'mattermost'（用于日志 / 监控 / 路由）。"""
    listener = MattermostListener(_make_settings())
    assert listener.name == "mattermost"
    # 也校验 class-level（不依赖实例）
    assert MattermostListener.name == "mattermost"
