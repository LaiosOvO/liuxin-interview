"""BotService.dispatch via HandlerRegistry 回归测试（ABS-05）。

目的：确保重构后 11 命令全部仍能正确分发到对应 handle_xxx 方法。

策略：
- 用 monkeypatch 替换每个 handle_xxx 为 AsyncMock，验证 dispatch 调用正确的 handler
- 不真触达 DB / FlowService — 只测路由
- 覆盖 11 个命令 + 未知命令 ValueError
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.services.bot_command_parser import BotCommand
from offboarding_flow.services.bot_service import BotInvocationContext, BotService


def _make_service() -> BotService:
    """造一个最小可用的 BotService — session / flow_service 用 mock。"""
    session = MagicMock()
    flow_service = MagicMock()
    return BotService(session=session, flow_service=flow_service)


def _hr_ctx() -> BotInvocationContext:
    return BotInvocationContext(
        user_name="hr.alice", user_id="hr_id", channel_id="C1", user_role="hr"
    )


@pytest.mark.asyncio
async def test_dispatch_help_routes_to_handle_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """help → handle_help 被调用 + 返回值原样回。"""
    svc = _make_service()
    monkeypatch.setattr(svc, "handle_help", lambda: "fake-help-reply")

    result = await svc.dispatch(BotCommand(name="help", args=(), raw="help"), _hr_ctx())

    assert result == "fake-help-reply"


@pytest.mark.asyncio
async def test_dispatch_start_routes_to_handle_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """start <username> → handle_start(username, ctx)。"""
    svc = _make_service()
    mock_handler = AsyncMock(return_value="fake-start-reply")
    monkeypatch.setattr(svc, "handle_start", mock_handler)

    ctx = _hr_ctx()
    result = await svc.dispatch(
        BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"), ctx
    )

    assert result == "fake-start-reply"
    mock_handler.assert_awaited_once_with("zhang.san", ctx)


@pytest.mark.asyncio
async def test_dispatch_start_self_apply_uses_user_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start __SELF__ → 用 ctx.user_name 当 employee_username。"""
    from offboarding_flow.services.bot_command_parser import SELF_APPLY_SENTINEL

    svc = _make_service()
    mock_handler = AsyncMock(return_value="self-start")
    monkeypatch.setattr(svc, "handle_start", mock_handler)

    ctx = _hr_ctx()  # user_name = hr.alice
    await svc.dispatch(BotCommand(name="start", args=(SELF_APPLY_SENTINEL,), raw="我要离职"), ctx)

    mock_handler.assert_awaited_once_with("hr.alice", ctx)


@pytest.mark.asyncio
async def test_dispatch_status_routes_to_handle_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """status <flow_id> → handle_status(flow_id)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="status-reply")
    monkeypatch.setattr(svc, "handle_status", mock)

    await svc.dispatch(
        BotCommand(name="status", args=("abc12345",), raw="status abc12345"), _hr_ctx()
    )

    mock.assert_awaited_once_with("abc12345")


@pytest.mark.asyncio
async def test_dispatch_report_routes_to_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """report → handle_report_stub。"""
    svc = _make_service()
    monkeypatch.setattr(svc, "handle_report_stub", lambda flow_id: f"report-{flow_id}")

    result = await svc.dispatch(
        BotCommand(name="report", args=("abc12345",), raw="report abc12345"), _hr_ctx()
    )

    assert result == "report-abc12345"


@pytest.mark.asyncio
async def test_dispatch_suggest_routes_to_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """suggest → handle_suggest_stub。"""
    svc = _make_service()
    monkeypatch.setattr(svc, "handle_suggest_stub", lambda flow_id: f"suggest-{flow_id}")

    result = await svc.dispatch(
        BotCommand(name="suggest", args=("abc",), raw="suggest abc"), _hr_ctx()
    )

    assert result == "suggest-abc"


@pytest.mark.asyncio
async def test_dispatch_list_routes_to_handle_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """list → handle_list(filter)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="list-reply")
    monkeypatch.setattr(svc, "handle_list", mock)

    await svc.dispatch(BotCommand(name="list", args=("active",), raw="list active"), _hr_ctx())

    mock.assert_awaited_once_with("active")


@pytest.mark.asyncio
async def test_dispatch_simulate_timeout_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """simulate-timeout → handle_simulate_timeout(flow_id, node_name)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="timeout-reply")
    monkeypatch.setattr(svc, "handle_simulate_timeout", mock)

    await svc.dispatch(
        BotCommand(
            name="simulate-timeout",
            args=("abc12345", "device_return"),
            raw="simulate-timeout abc12345 device_return",
        ),
        _hr_ctx(),
    )

    mock.assert_awaited_once_with("abc12345", "device_return")


@pytest.mark.asyncio
async def test_dispatch_simulate_evidence_missing_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """simulate-evidence-missing → handle_simulate_evidence_missing(flow_id, node_name)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="evidence-reply")
    monkeypatch.setattr(svc, "handle_simulate_evidence_missing", mock)

    await svc.dispatch(
        BotCommand(
            name="simulate-evidence-missing",
            args=("xyz", "finance_settle"),
            raw="simulate-evidence-missing xyz finance_settle",
        ),
        _hr_ctx(),
    )

    mock.assert_awaited_once_with("xyz", "finance_settle")


@pytest.mark.asyncio
async def test_dispatch_meeting_ingest_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """meeting-ingest → handle_meeting_ingest(text, ctx)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="ingest-reply")
    monkeypatch.setattr(svc, "handle_meeting_ingest", mock)

    ctx = _hr_ctx()
    await svc.dispatch(
        BotCommand(
            name="meeting-ingest", args=("会议纪要文本",), raw="meeting-ingest 会议纪要文本"
        ),
        ctx,
    )

    mock.assert_awaited_once_with("会议纪要文本", ctx)


@pytest.mark.asyncio
async def test_dispatch_meeting_list_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """meeting-list → handle_meeting_list(ctx)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="meeting-list-reply")
    monkeypatch.setattr(svc, "handle_meeting_list", mock)

    ctx = _hr_ctx()
    await svc.dispatch(BotCommand(name="meeting-list", args=(), raw="meeting-list"), ctx)

    mock.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_dispatch_users_sync_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """users-sync → handle_users_sync(ctx)。"""
    svc = _make_service()
    mock = AsyncMock(return_value="users-sync-reply")
    monkeypatch.setattr(svc, "handle_users_sync", mock)

    ctx = _hr_ctx()
    await svc.dispatch(BotCommand(name="users-sync", args=(), raw="users-sync"), ctx)

    mock.assert_awaited_once_with(ctx)


@pytest.mark.asyncio
async def test_dispatch_unknown_command_raises_value_error() -> None:
    """未注册命令 → ValueError（保持向后兼容旧 dispatch 行为）。"""
    svc = _make_service()

    with pytest.raises(ValueError, match="未实现的命令分支"):
        await svc.dispatch(BotCommand(name="totally-unknown", args=(), raw=""), _hr_ctx())


def test_registry_has_all_11_commands_registered() -> None:
    """BotService 构造后 registry 应已注册全部 11 命令。"""
    svc = _make_service()

    expected = {
        "help",
        "start",
        "status",
        "report",
        "suggest",
        "list",
        "simulate-timeout",
        "simulate-evidence-missing",
        "meeting-ingest",
        "meeting-list",
        "users-sync",
    }
    registered = set(svc._registry.list_commands())
    assert (
        registered == expected
    ), f"缺命令: {expected - registered}; 多命令: {registered - expected}"
