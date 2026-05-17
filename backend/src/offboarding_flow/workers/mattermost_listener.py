"""Mattermost WebSocket listener — 用 bot token 长连接监听消息（DM + channel）。

设计目的（用户要求）：
- bot 在 Mattermost 显示为**在线**（不是 outgoing webhook 那种离线被动模式）
- 同时支持 **DM** 与 **channel @mention** 两种触发场景
- 命令解析复用 bot_command_parser + bot_service（与 outgoing webhook 走同一套逻辑）

实现机制：
- 使用 mattermostautodriver.AsyncDriver.init_websocket(handler) 长连
- handler 接收每条 WS 事件，过滤 `posted` 事件
- 提取 post.message + channel_type → DM 或 channel @mention 才处理
- 解析 → dispatch → 用 driver.posts.create_post 主动 POST 回复

幂等性：
- bot 自己发的消息（user_id == bot_user_id）必须跳过，否则死循环

优雅停止：
- FastAPI lifespan shutdown 时 cancel task + driver.disconnect()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

# httpx 0.28+ 移除 `proxies` 参数，mattermostautodriver 2.0 还在传 → monkey-patch 兼容
import httpx as _httpx

_orig_async_client_init = _httpx.AsyncClient.__init__


def _patched_async_client_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.pop("proxies", None)
    return _orig_async_client_init(self, *args, **kwargs)


_httpx.AsyncClient.__init__ = _patched_async_client_init  # type: ignore[method-assign]

from mattermostautodriver import AsyncDriver  # noqa: E402
from sqlalchemy import select  # noqa: E402

from offboarding_flow.config import Settings  # noqa: E402
from offboarding_flow.im.context import IMHelpers  # noqa: E402
from offboarding_flow.im.protocol import DispatchFn  # noqa: E402
from offboarding_flow.state_store.models import User  # noqa: E402
from offboarding_flow.state_store.session import new_session  # noqa: E402

logger = logging.getLogger(__name__)


class MattermostListener:
    """Mattermost WebSocket 长连接 listener — 让 bot 在线 + DM 工作。

    实现 `offboarding_flow.im.protocol.IMListener` Protocol（ABS-01 / ABS-04）：
    - `name = "mattermost"` 标识平台
    - `async start / stop`            生命周期
    - `register_command_listener`     反向注入 dispatch（统一 dispatch_message）

    与 Plan 08-01 前的版本相比：
    - 行 175-262 的 dispatch 业务编排已搬到 `im.dispatcher.dispatch_message`
    - listener 现在仅负责：解 WS event → 触发条件过滤 → 构造 IMHelpers → 转交 dispatch
    """

    # IMListener Protocol — 平台名（"mattermost"）
    name: str = "mattermost"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: AsyncDriver | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        # 注入的统一 dispatch（由 main.py lifespan 通过 register_command_listener 设置）
        self._dispatch: DispatchFn | None = None

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        """ABS-04 反向订阅 hook — 让 listener 收到合法消息时调统一 dispatch。

        通常由 FastAPI lifespan 在创建 listener 后立即调用：
            mm_listener.register_command_listener(dispatch_message)
        """
        self._dispatch = dispatch
        logger.info("[mm_listener] dispatch listener registered: %s", dispatch.__name__)

    async def start(self) -> None:
        """启动 WebSocket listener（lifespan 调）。"""
        if self._task is not None:
            logger.warning("[mm_listener] already running, skip start")
            return
        if not self.settings.mattermost_bot_token or self.settings.mattermost_bot_token.startswith(
            "changeme"
        ):
            logger.warning("[mm_listener] BOT_TOKEN 未设置，跳过 WebSocket 监听")
            return
        self._task = asyncio.create_task(self._run(), name="mattermost-listener")
        logger.info("[mm_listener] started bot=%s", self.settings.mattermost_bot_username)

    async def stop(self) -> None:
        """优雅停止（lifespan shutdown 调）。"""
        self._stop_event.set()
        if self.driver is not None:
            try:
                await self.driver.disconnect()
            except Exception as e:
                logger.debug("[mm_listener] disconnect: %s", e)
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        logger.info("[mm_listener] stopped")

    async def _run(self) -> None:
        """主循环：连 WebSocket，断了重连。"""
        url = self.settings.mattermost_url.replace("http://", "").replace("https://", "")
        host, _, port_str = url.partition(":")
        port = int(port_str) if port_str else 8065
        scheme = "https" if self.settings.mattermost_url.startswith("https://") else "http"

        while not self._stop_event.is_set():
            try:
                self.driver = AsyncDriver(
                    {
                        "url": host,
                        "port": port,
                        "scheme": scheme,
                        "token": self.settings.mattermost_bot_token,
                        "verify": False,
                        "timeout": 30,
                    }
                )
                await self.driver.login()
                logger.info(
                    "[mm_listener] connected, bot_user_id=%s", self.settings.mattermost_bot_user_id
                )
                await self.driver.init_websocket(self._handle_event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[mm_listener] websocket error, reconnect in 5s: %s", e)
                await asyncio.sleep(5)

    async def _handle_event(self, event_str: str) -> None:
        """WS 事件 handler（每条 JSON event 一次）。"""
        try:
            event = json.loads(event_str) if isinstance(event_str, str) else event_str
        except Exception:
            return
        if event.get("event") != "posted":
            return
        data = event.get("data", {})
        post_str = data.get("post")
        if not post_str:
            return
        try:
            post = json.loads(post_str) if isinstance(post_str, str) else post_str
        except Exception:
            return

        bot_user_id = self.settings.mattermost_bot_user_id
        post_user_id = post.get("user_id", "")
        # 跳过 bot 自己的消息防死循环
        if post_user_id == bot_user_id:
            return

        message = post.get("message", "").strip()
        channel_id = post.get("channel_id", "")
        channel_type = data.get("channel_type", "")  # 'D' = DM, 'O' = public, 'P' = private
        sender_name = data.get("sender_name", "").lstrip("@")

        # 触发条件：DM 任意消息 / channel 里 @ 了 bot / 含中文 trigger 词
        bot_mention = f"@{self.settings.mattermost_bot_username}"
        is_dm = channel_type == "D"
        is_at_mentioned = bot_mention in message
        contains_trigger = any(
            kw in message for kw in ("我要离职", "申请离职", "离职申请", "offboarding-bot")
        )
        if not (is_dm or is_at_mentioned or contains_trigger):
            return

        logger.info(
            "[mm_listener] handling msg from=%s channel=%s is_dm=%s text=%r",
            sender_name,
            channel_id[:8],
            is_dm,
            message[:80],
        )

        # ABS-02：把"消息 → 业务命令"完全交给 im.dispatcher.dispatch_message
        # listener 只负责 WS event 拆解 + 触发过滤 + 构造平台无关的 IMHelpers
        if self._dispatch is None:
            logger.warning(
                "[mm_listener] dispatch 未注册（main.py lifespan 未调 register_command_listener），丢弃消息：%s",
                message[:80],
            )
            return

        helpers = IMHelpers(
            post_channel=self._post_reply,
            send_dm=self._send_dm_by_username,
            ensure_in_channel=self._ensure_user_in_channel,
        )
        await self._dispatch(
            sender_username=sender_name,
            user_id=post_user_id,
            channel_id=channel_id,
            channel_type=channel_type,
            message=message,
            im_helpers=helpers,
            settings=self.settings,
            session_factory=new_session,
        )

    @staticmethod
    async def _resolve_user_role(session: Any, user_name: str) -> str | None:
        stmt = select(User).where(User.username == user_name)
        user = (await session.execute(stmt)).scalar_one_or_none()
        return user.role if user else None

    async def _post_reply(self, channel_id: str, message: str) -> None:
        """用 bot token 主动 POST 消息到 channel/DM。"""
        if self.driver is None or not channel_id:
            return
        try:
            await self.driver.posts.create_post({"channel_id": channel_id, "message": message})
        except Exception as e:
            logger.warning("[mm_listener] post_reply failed channel=%s: %s", channel_id[:8], e)

    async def _ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        """把 user 加进 channel — @mention 才能真触发通知。已是成员的会幂等。"""
        if self.driver is None or not channel_id or not username:
            return
        try:
            user = await self.driver.users.get_user_by_username(username)
            await self.driver.channels.add_user(channel_id, {"user_id": user["id"]})
        except Exception as e:
            # 已是成员会返 错误，吞掉
            logger.debug("[mm_listener] add %s to channel %s: %s", username, channel_id[:8], e)

    async def _send_dm_by_username(self, username: str, message: str) -> None:
        """按 MM username 查 user_id → 与 bot 创建/获取 DM channel → POST 消息。"""
        if self.driver is None or not username:
            return
        try:
            user = await self.driver.users.get_user_by_username(username)
            target_id = user["id"]
            bot_id = self.settings.mattermost_bot_user_id
            dm = await self.driver.channels.create_direct_channel([bot_id, target_id])
            await self.driver.posts.create_post({"channel_id": dm["id"], "message": message})
            logger.info("[mm_listener] DM sent to %s (channel=%s)", username, dm["id"][:8])
        except Exception as e:
            logger.warning("[mm_listener] send_dm to %s failed: %s", username, e)
