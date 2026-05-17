"""dispatch_message 单元测试（ABS-02）。

覆盖 6 个分支（合 happy path + 4 错误分支 + intent router fallback）：
1. 合法命令（"help"） → BotService.dispatch 返回 reply → post_channel 写回
2. parse 失败 + intent_router 路由出合法命令 → BotService.dispatch → 写回
3. parse 失败 + intent_router 返回 None (ai_qa) → ai_reply 直接写回 + 提前 return
4. BotFlowNotFoundError → "⚠️" 友好 markdown 写回
5. BotPermissionError → "🚫" 拒绝提示写回
6. 未知 Exception → 通用错误提示 + log

测试约定（tests/unit/ — 单测）：
- post_channel / send_dm 用 AsyncMock 验证回写参数
- BotService.dispatch / BotIntentRouter 用 monkeypatch 替换为 mock
- session_factory 用 async context manager + AsyncMock session（不 mock 整 DB，
  只 mock execute 返回；真 DB 集成测试在 Task 3 的 integration 测试）
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.im.context import IMHelpers
from offboarding_flow.im.dispatcher import dispatch_message
from offboarding_flow.services.bot_command_parser import BotCommand
from offboarding_flow.services.bot_service import (
    BotFlowNotFoundError,
    BotPermissionError,
)

# ───────── Fixtures ─────────


@pytest.fixture
def post_channel_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def send_dm_mock() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def im_helpers(post_channel_mock: AsyncMock, send_dm_mock: AsyncMock) -> IMHelpers:
    return IMHelpers(
        post_channel=post_channel_mock,
        send_dm=send_dm_mock,
        ensure_in_channel=AsyncMock(),
    )


def _make_session_factory(user_role: str | None = "hr") -> Any:
    """造一个 async context manager session_factory；user 查询返回 mock User 或 None。"""

    @asynccontextmanager
    async def factory():
        session = MagicMock()
        # _resolve_user_role 内部：result = await session.execute(stmt); user = result.scalar_one_or_none()
        result_mock = MagicMock()
        if user_role is not None:
            user_mock = MagicMock()
            user_mock.role = user_role
            result_mock.scalar_one_or_none.return_value = user_mock
        else:
            result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)
        yield session

    return factory


def _make_settings() -> Any:
    s = MagicMock()
    s.mattermost_url = "http://mm:8065"
    s.mattermost_bot_token = "fake-token"
    s.mattermost_bot_username = "offboarding-bot"
    return s


@pytest.fixture(autouse=True)
def _stub_heavy_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """统一 stub get_graph / FlowService / OutboxRepository / NotificationService / FlowRepository 等
    避免单测路径触达 DB 与 LangGraph 实例。"""
    monkeypatch.setattr(
        "offboarding_flow.flow_engine.graph.get_graph",
        lambda: MagicMock(name="StubGraph"),
    )
    monkeypatch.setattr(
        "offboarding_flow.services.FlowService",
        lambda *a, **kw: MagicMock(name="StubFlowService"),
    )
    monkeypatch.setattr(
        "offboarding_flow.services.NotificationService",
        lambda *a, **kw: MagicMock(name="StubNotif"),
    )
    monkeypatch.setattr(
        "offboarding_flow.notifications.outbox_repository.OutboxRepository",
        lambda *a, **kw: MagicMock(name="StubOutbox"),
    )
    monkeypatch.setattr(
        "offboarding_flow.state_store.repositories.FlowRepository",
        lambda *a, **kw: MagicMock(name="StubFlowRepo"),
    )
    monkeypatch.setattr(
        "offboarding_flow.state_store.repositories.NodeRepository",
        lambda *a, **kw: MagicMock(name="StubNodeRepo"),
    )
    monkeypatch.setattr(
        "offboarding_flow.state_store.repositories.ActionRepository",
        lambda *a, **kw: MagicMock(name="StubActionRepo"),
    )


# ───────── 测试 1：合法命令 happy path ─────────


@pytest.mark.asyncio
async def test_dispatch_legal_help_command_writes_reply_back(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 1：用户发 'help' → parse OK → bot_service.dispatch 返回 reply → post_channel 写回。"""
    # mock BotService.dispatch 返回固定回复
    fake_reply = "🤖 [测试 help 回复]"
    dispatch_mock = AsyncMock(return_value=fake_reply)
    monkeypatch.setattr("offboarding_flow.im.dispatcher.BotService.dispatch", dispatch_mock)
    # mock FlowService / 其他构造（避免触达 DB）
    monkeypatch.setattr(
        "offboarding_flow.flow_engine.graph.get_graph",
        lambda: MagicMock(),
    )

    await dispatch_message(
        sender_username="hr.alice",
        user_id="mm_user_1",
        channel_id="ch1",
        channel_type="D",
        message="help",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory("hr"),
    )

    post_channel_mock.assert_awaited_once_with("ch1", fake_reply)
    dispatch_mock.assert_awaited_once()


# ───────── 测试 2：parse 失败 + intent_router 路由出命令 ─────────


@pytest.mark.asyncio
async def test_dispatch_intent_router_fallback_routes_to_command(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 2：natural language → parse 失败 → router 路由出 help cmd → dispatch."""
    fake_reply = "🤖 [router 路由后回复]"
    # 让 BotIntentRouter.classify 返回一个能被 intent_to_bot_command 转出 help cmd 的结果
    fake_router = MagicMock()
    fake_router.classify = AsyncMock(
        return_value=MagicMock(intent="help", confidence=0.95, args={}, ai_reply=None, raw="{}")
    )
    fake_router.intent_to_bot_command = MagicMock(
        return_value=BotCommand(name="help", args=(), raw="help")
    )
    monkeypatch.setattr(
        "offboarding_flow.services.bot_intent_router.BotIntentRouter",
        lambda *a, **kw: fake_router,
    )
    monkeypatch.setattr(
        "offboarding_flow.im.dispatcher.BotService.dispatch",
        AsyncMock(return_value=fake_reply),
    )

    await dispatch_message(
        sender_username="hr.alice",
        user_id="mm_u",
        channel_id="ch2",
        channel_type="D",
        message="嗨，你能干啥",  # natural language → parse 失败
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory("hr"),
    )

    post_channel_mock.assert_awaited_once_with("ch2", fake_reply)
    fake_router.classify.assert_awaited_once()


# ───────── 测试 3：parse 失败 + router 返 None (ai_qa) ─────────


@pytest.mark.asyncio
async def test_dispatch_intent_router_ai_qa_fallback_uses_ai_reply(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 3：router 返 None + 有 ai_reply → ai_reply 直接写回 + 不再走 dispatch."""
    fake_router = MagicMock()
    fake_router.classify = AsyncMock(
        return_value=MagicMock(
            intent="ai_qa",
            confidence=0.3,
            args={},
            ai_reply="🤖 AI 回答：测试 ai_qa 兜底",
            raw="{}",
        )
    )
    fake_router.intent_to_bot_command = MagicMock(return_value=None)
    monkeypatch.setattr(
        "offboarding_flow.services.bot_intent_router.BotIntentRouter",
        lambda *a, **kw: fake_router,
    )
    dispatch_mock = AsyncMock()
    monkeypatch.setattr("offboarding_flow.im.dispatcher.BotService.dispatch", dispatch_mock)

    await dispatch_message(
        sender_username="zhang.san",
        user_id="mm_u",
        channel_id="ch3",
        channel_type="D",
        message="今天天气真好",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory(None),  # zhang.san 未注册
    )

    post_channel_mock.assert_awaited_once_with("ch3", "🤖 AI 回答：测试 ai_qa 兜底")
    dispatch_mock.assert_not_awaited()  # ai_qa 不再走业务 dispatch


@pytest.mark.asyncio
async def test_dispatch_intent_router_returns_none_without_ai_reply_uses_default(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 3b：router 返 None + ai_reply None → 默认友好提示。"""
    fake_router = MagicMock()
    fake_router.classify = AsyncMock(
        return_value=MagicMock(intent="ai_qa", confidence=0.1, args={}, ai_reply=None, raw="{}")
    )
    fake_router.intent_to_bot_command = MagicMock(return_value=None)
    monkeypatch.setattr(
        "offboarding_flow.services.bot_intent_router.BotIntentRouter",
        lambda *a, **kw: fake_router,
    )

    await dispatch_message(
        sender_username="z",
        user_id="u",
        channel_id="ch3b",
        channel_type="D",
        message="abc",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory(None),
    )

    post_channel_mock.assert_awaited_once()
    call_args = post_channel_mock.call_args
    assert call_args[0][0] == "ch3b"
    assert "我没听懂" in call_args[0][1]
    assert "@offboarding-bot help" in call_args[0][1]


@pytest.mark.asyncio
async def test_dispatch_intent_router_exception_falls_back_to_parse_error_hint(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 3c：router 自身抛异常 → 写回 parse error + 帮助提示。"""
    fake_router = MagicMock()
    fake_router.classify = AsyncMock(side_effect=RuntimeError("LLM 宕机"))
    monkeypatch.setattr(
        "offboarding_flow.services.bot_intent_router.BotIntentRouter",
        lambda *a, **kw: fake_router,
    )

    await dispatch_message(
        sender_username="z",
        user_id="u",
        channel_id="ch3c",
        channel_type="D",
        message="xxxxx",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory(None),
    )

    post_channel_mock.assert_awaited_once()
    call_args = post_channel_mock.call_args
    assert call_args[0][0] == "ch3c"
    assert "⚠️" in call_args[0][1]
    assert "help" in call_args[0][1]


# ───────── 测试 4：BotFlowNotFoundError ─────────


@pytest.mark.asyncio
async def test_dispatch_flow_not_found_error_writes_warning_reply(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 4：BotService.dispatch 抛 BotFlowNotFoundError → 用 ⚠️ 友好回写。"""
    monkeypatch.setattr(
        "offboarding_flow.im.dispatcher.BotService.dispatch",
        AsyncMock(side_effect=BotFlowNotFoundError("案件 ID 不存在: abc12345")),
    )

    await dispatch_message(
        sender_username="hr.alice",
        user_id="u",
        channel_id="ch4",
        channel_type="D",
        message="status abc12345",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory("hr"),
    )

    post_channel_mock.assert_awaited_once()
    call_args = post_channel_mock.call_args
    assert call_args[0][0] == "ch4"
    assert "⚠️" in call_args[0][1]
    assert "abc12345" in call_args[0][1]


# ───────── 测试 5：BotPermissionError ─────────


@pytest.mark.asyncio
async def test_dispatch_permission_error_writes_refusal_reply(
    monkeypatch: pytest.MonkeyPatch,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 5：BotService.dispatch 抛 BotPermissionError → 🚫 拒绝提示。"""
    monkeypatch.setattr(
        "offboarding_flow.im.dispatcher.BotService.dispatch",
        AsyncMock(side_effect=BotPermissionError("权限不足：HR 才能 start")),
    )

    await dispatch_message(
        sender_username="zhang.san",
        user_id="u",
        channel_id="ch5",
        channel_type="D",
        message="start someone.else",
        im_helpers=im_helpers,
        settings=_make_settings(),
        session_factory=_make_session_factory("applicant"),
    )

    post_channel_mock.assert_awaited_once()
    call_args = post_channel_mock.call_args
    assert call_args[0][0] == "ch5"
    assert "🚫" in call_args[0][1]
    assert "权限不足" in call_args[0][1]


# ───────── 测试 6：未知 Exception ─────────


@pytest.mark.asyncio
async def test_dispatch_unknown_exception_writes_generic_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    im_helpers: IMHelpers,
    post_channel_mock: AsyncMock,
) -> None:
    """场景 6：BotService.dispatch 抛未知 Exception → 通用错误回写 + log."""
    monkeypatch.setattr(
        "offboarding_flow.im.dispatcher.BotService.dispatch",
        AsyncMock(side_effect=RuntimeError("DB 连接突然挂了")),
    )

    import logging

    with caplog.at_level(logging.ERROR, logger="offboarding_flow.im.dispatcher"):
        await dispatch_message(
            sender_username="hr.alice",
            user_id="u",
            channel_id="ch6",
            channel_type="D",
            message="help",
            im_helpers=im_helpers,
            settings=_make_settings(),
            session_factory=_make_session_factory("hr"),
        )

    post_channel_mock.assert_awaited_once()
    call_args = post_channel_mock.call_args
    assert call_args[0][0] == "ch6"
    assert "命令处理失败" in call_args[0][1]
    # caplog 应捕获到 logger.exception 输出（dispatch error: ...）
    assert any("dispatch error" in r.message for r in caplog.records)
