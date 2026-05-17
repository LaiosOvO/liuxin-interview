"""BotService HandlerRegistry — 把 dispatch if/elif 重构为动态查表（ABS-05）。

设计目标：
- 把 BotService.dispatch 内 11 个 `if cmd.name == "xxx"` 分支替换为
  `await self._registry.invoke(cmd, ctx)`。
- 每个 handler 在 BotService.__init__ 内通过 `_register_handlers()` 注册。
- 未注册命令 → 抛 UnknownBotCommandError（之前是 ValueError，区分更清晰）。
- 新加命令时：写 handler + 在 _register_handlers 加一行 `registry.register("foo", self.handle_foo)`，
  完全免动 dispatch 函数。

为什么不用全局 decorator（如 `@bot_command("help")`）：
- BotService 实例化时才有 self / session / flow_service 上下文
- 全局 decorator 需要类级别注册 + 实例 binding，工程复杂度高于收益
- 显式 `_register_handlers()` 在 __init__ 一次注册，简单清晰

参考：agent-builder 项目的 `IM bot 抽象草图` (docs/plans/2026-05-17-im-bot-abstraction-design.md)。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from offboarding_flow.services.bot_command_parser import BotCommand
    from offboarding_flow.services.bot_service import BotInvocationContext

logger = logging.getLogger(__name__)

# Handler 统一签名：接收 (cmd, ctx) → 返回 str（回复文本）。
# 用 Awaitable[str] 是因为有 sync handler（help / report_stub） 也用 await — 我们统一
# wrap 在 async 函数里，或者让 registry 自动判断 awaitable。简化起见统一 async。
BotHandler = Callable[["BotCommand", "BotInvocationContext"], Awaitable[str]]


class UnknownBotCommandError(Exception):
    """命令未注册到 HandlerRegistry — 通常意味着 bot_command_parser 解出了
    新命令但 BotService 还没加 handler。"""


class BotHandlerRegistry:
    """命令 → handler 的动态查表分发器（ABS-05）。

    Usage:
        registry = BotHandlerRegistry()
        registry.register("help", self.handle_help)
        registry.register("start", self.handle_start)
        ...
        reply = await registry.invoke(cmd, ctx)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, BotHandler] = {}

    def register(self, cmd_name: str, handler: BotHandler) -> None:
        """注册 handler — 同名 handler 二次注册抛 ValueError 防止意外覆盖。"""
        if cmd_name in self._handlers:
            raise ValueError(
                f"命令 '{cmd_name}' 已注册（防止意外重复注册导致 dispatch 行为不确定）"
            )
        self._handlers[cmd_name] = handler
        logger.debug("[bot-registry] registered handler: %s", cmd_name)

    def has(self, cmd_name: str) -> bool:
        """检查命令是否已注册。"""
        return cmd_name in self._handlers

    def list_commands(self) -> list[str]:
        """列出所有已注册命令名 — 用于 help / 监控 / 测试。"""
        return sorted(self._handlers.keys())

    async def invoke(self, cmd: "BotCommand", ctx: "BotInvocationContext") -> str:
        """按 cmd.name 查表 → 调用 handler 返回回复。

        未注册命令抛 UnknownBotCommandError。
        Handler 自身的业务异常（BotPermissionError / BotFlowNotFoundError 等）原样抛出，
        由 webhook / dispatcher 统一捕获。
        """
        handler = self._handlers.get(cmd.name)
        if handler is None:
            raise UnknownBotCommandError(
                f"未注册命令: '{cmd.name}'（已注册: {self.list_commands()}）"
            )
        return await handler(cmd, ctx)


__all__ = ["BotHandlerRegistry", "BotHandler", "UnknownBotCommandError"]
