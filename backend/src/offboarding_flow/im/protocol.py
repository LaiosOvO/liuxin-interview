"""IMListener Protocol — IM 平台被动监听通道抽象（ABS-01 / ABS-04）。

设计要点：
- 用 `typing.Protocol + @runtime_checkable` — 实现方无需 explicit 继承，
  通过结构子类型 + `isinstance()` 即可校验。
- listener 自己**不知道**业务命令；通过 `register_command_listener` 注入
  统一的 `dispatch` 函数（即 `im.dispatcher.dispatch_message`）。
- 生命周期方法 `start / stop` 由 FastAPI lifespan 调度。

跨平台示例：
- `MattermostListener` 用 WebSocket 长连，收到 posted 事件 → 调 self._dispatch
- `HulyListener` 用 HTTP webhook，收到 sidecar 推送 → 同样调 self._dispatch
- 两者公用 `dispatch_message` 这一份业务编排逻辑
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol, runtime_checkable

# `dispatch_message` 的可调用签名（实际签名见 im.dispatcher）。
# 使用 `Callable[..., Awaitable[None]]` 而非完全展开签名，
# 避免与 IMHelpers / Settings 形成强耦合（Protocol 关心的是"能调用"）。
DispatchFn = Callable[..., Awaitable[None]]


@runtime_checkable
class IMListener(Protocol):
    """IM 平台监听器协议 — 任何 IM 实现（MM / Huly / Lark / WeCom）都遵循此契约。

    最小实现 = 4 个成员：
    - `name`               (class attribute) — 平台标识；用于日志 / 监控 / 路由
    - `async start`        — 启动监听（lifespan startup 调用，幂等）
    - `async stop`         — 优雅停止（lifespan shutdown 调用，幂等）
    - `register_command_listener` — 在 listener 收到合法消息时调用注入的 dispatch
    """

    # 平台名（"mattermost" | "huly" | "lark" | ...）
    name: str

    async def start(self) -> None:
        """启动监听（lifespan 内一次性调用，必须幂等）。

        实现方在此建立到 IM 平台的长连接 / Webhook 订阅 / HTTP 轮询。
        如果配置缺失（token / URL 未设），应 log warning 后直接返回（不抛）。
        """
        ...

    async def stop(self) -> None:
        """优雅停止（lifespan shutdown 调用，必须幂等）。

        实现方在此关闭长连接 / 取消订阅 / 等待背景 task 终止。
        """
        ...

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        """反向订阅 hook（ABS-04）— 让 listener 在合法消息时调统一 dispatch。

        Args:
            dispatch: 通常即 `im.dispatcher.dispatch_message`；listener 仅
                负责"接消息 + 拆 channel/sender" 然后转交，**不负责**业务逻辑。

        实现方一般把传入的 dispatch 存到 `self._dispatch`，事件 handler 内
        调 `await self._dispatch(...)`。如果 dispatch 未注册，应 log warning
        + 丢弃消息（防止 listener 静默处理）。
        """
        ...


__all__ = ["IMListener", "DispatchFn"]
