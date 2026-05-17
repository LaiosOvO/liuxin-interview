"""BotHandlerRegistry 单元测试（ABS-05 — bot_service.dispatch 重构）。

覆盖：
1. register + invoke 单 handler → 调到对应 handler
2. 未注册命令 → 抛 UnknownBotCommandError
3. has() 检查
4. list_commands() 排序输出
5. 重复 register 抛 ValueError（防意外覆盖）
6. handler 抛业务异常 → 原样上抛（不被 Registry 吞）
7. 多 handler 注册场景 — 11 命令全注册场景模拟
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from offboarding_flow.services.bot_command_parser import BotCommand
from offboarding_flow.services.bot_handler_registry import (
    BotHandlerRegistry,
    UnknownBotCommandError,
)


@pytest.fixture
def fake_ctx() -> MagicMock:
    """构造一个 BotInvocationContext mock（仅 invoke 测试用）。"""
    ctx = MagicMock()
    ctx.user_name = "hr.alice"
    ctx.user_role = "hr"
    return ctx


def _make_cmd(name: str, *args: str) -> BotCommand:
    return BotCommand(name=name, args=tuple(args), raw=f"{name} {' '.join(args)}".strip())


@pytest.mark.asyncio
async def test_register_and_invoke_calls_handler(fake_ctx) -> None:
    """register + invoke → handler 被调用，返回值原样返回。"""
    registry = BotHandlerRegistry()

    called: dict = {}

    async def my_handler(cmd, ctx) -> str:
        called["cmd"] = cmd
        called["ctx"] = ctx
        return f"handled-{cmd.name}"

    registry.register("foo", my_handler)
    result = await registry.invoke(_make_cmd("foo"), fake_ctx)

    assert result == "handled-foo"
    assert called["cmd"].name == "foo"
    assert called["ctx"] is fake_ctx


@pytest.mark.asyncio
async def test_invoke_unregistered_command_raises_unknown_error(fake_ctx) -> None:
    """未注册命令 → 抛 UnknownBotCommandError。"""
    registry = BotHandlerRegistry()

    with pytest.raises(UnknownBotCommandError, match="未注册命令: 'unknown'"):
        await registry.invoke(_make_cmd("unknown"), fake_ctx)


@pytest.mark.asyncio
async def test_register_twice_raises_value_error() -> None:
    """同名 handler 重复 register → ValueError 防意外覆盖。"""
    registry = BotHandlerRegistry()

    async def h1(cmd, ctx) -> str:
        return "h1"

    async def h2(cmd, ctx) -> str:
        return "h2"

    registry.register("foo", h1)

    with pytest.raises(ValueError, match="已注册"):
        registry.register("foo", h2)


def test_has_returns_correct_status() -> None:
    """has() 反映命令是否已注册。"""
    registry = BotHandlerRegistry()

    async def noop(cmd, ctx) -> str:
        return ""

    assert registry.has("foo") is False
    registry.register("foo", noop)
    assert registry.has("foo") is True
    assert registry.has("bar") is False


def test_list_commands_returns_sorted_names() -> None:
    """list_commands() 返回字母序排序的命令名 list。"""
    registry = BotHandlerRegistry()

    async def noop(cmd, ctx) -> str:
        return ""

    registry.register("zebra", noop)
    registry.register("apple", noop)
    registry.register("mango", noop)

    assert registry.list_commands() == ["apple", "mango", "zebra"]


@pytest.mark.asyncio
async def test_handler_business_exception_propagates_unchanged(fake_ctx) -> None:
    """handler 抛业务异常（如 BotPermissionError） → registry 不吞，原样上抛。"""
    from offboarding_flow.services.bot_service import BotPermissionError

    registry = BotHandlerRegistry()

    async def failing_handler(cmd, ctx) -> str:
        raise BotPermissionError("权限不足：只有 HR 能 start")

    registry.register("start", failing_handler)

    with pytest.raises(BotPermissionError, match="权限不足"):
        await registry.invoke(_make_cmd("start", "zhang.san"), fake_ctx)


@pytest.mark.asyncio
async def test_handler_arbitrary_exception_propagates(fake_ctx) -> None:
    """handler 抛任意 Exception → registry 不吞 + 不 wrap。"""
    registry = BotHandlerRegistry()

    async def boom(cmd, ctx) -> str:
        raise RuntimeError("DB 突然挂了")

    registry.register("status", boom)

    with pytest.raises(RuntimeError, match="DB 突然挂了"):
        await registry.invoke(_make_cmd("status", "abc12345"), fake_ctx)


@pytest.mark.asyncio
async def test_multiple_handlers_dispatch_independently(fake_ctx) -> None:
    """注册多个 handler → 不同命令各自走对应 handler。"""
    registry = BotHandlerRegistry()

    async def h_a(cmd, ctx) -> str:
        return "A"

    async def h_b(cmd, ctx) -> str:
        return "B"

    async def h_c(cmd, ctx) -> str:
        return "C"

    registry.register("a", h_a)
    registry.register("b", h_b)
    registry.register("c", h_c)

    assert await registry.invoke(_make_cmd("a"), fake_ctx) == "A"
    assert await registry.invoke(_make_cmd("b"), fake_ctx) == "B"
    assert await registry.invoke(_make_cmd("c"), fake_ctx) == "C"


def test_unknown_command_error_lists_registered_commands(fake_ctx) -> None:
    """UnknownBotCommandError 错误信息含已注册命令列表（便于排错）。"""
    registry = BotHandlerRegistry()

    async def noop(cmd, ctx) -> str:
        return ""

    registry.register("help", noop)
    registry.register("start", noop)

    # 不真 invoke，看错误信息构造
    import asyncio

    with pytest.raises(UnknownBotCommandError) as exc_info:
        asyncio.run(registry.invoke(_make_cmd("foo"), fake_ctx))

    assert "未注册命令" in str(exc_info.value)
    assert "help" in str(exc_info.value)
    assert "start" in str(exc_info.value)
