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
from offboarding_flow.services.bot_command_parser import (  # noqa: E402
    BotCommandParseError,
    parse_command,
)
from offboarding_flow.services.bot_service import (  # noqa: E402
    BotFlowNotFoundError,
    BotInvocationContext,
    BotPermissionError,
    BotService,
)
from offboarding_flow.state_store.models import User  # noqa: E402
from offboarding_flow.state_store.session import new_session  # noqa: E402

logger = logging.getLogger(__name__)


class MattermostListener:
    """Mattermost WebSocket 长连接 listener — 让 bot 在线 + DM 工作。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.driver: AsyncDriver | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

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

        try:
            cmd = parse_command(message)
        except BotCommandParseError as e:
            # LLM intent router 兜底：白名单失败 → 自然语言意图分类 / 通用 AI 问答
            from offboarding_flow.services.bot_intent_router import BotIntentRouter

            try:
                # 先查 sender role（与下面 dispatch 一致）
                async with new_session() as s2:
                    sender_role = await self._resolve_user_role(s2, sender_name)
                router = BotIntentRouter()
                ir = await router.classify(
                    message=message,
                    sender_username=sender_name,
                    sender_role=sender_role,
                )
                logger.info(
                    "[mm_listener] intent=%s conf=%.2f args=%s",
                    ir.intent,
                    ir.confidence,
                    list(ir.args.keys()),
                )
                fallback_cmd = router.intent_to_bot_command(ir, sender_name)
                if fallback_cmd is None:
                    # ai_qa 路径 — 直接发 LLM 回答
                    ai_text = ir.ai_reply or (
                        "🤖 我没听懂你的意思。可以试试：\n"
                        "- `@offboarding-bot help` 看命令清单\n"
                        "- 直接发 `我要离职` 自助起流程\n"
                        "- 粘贴会议纪要让我整理"
                    )
                    await self._post_reply(channel_id, ai_text)
                    return
                cmd = fallback_cmd
            except Exception as router_exc:
                logger.warning("[mm_listener] intent router 失败: %s", router_exc)
                await self._post_reply(
                    channel_id,
                    f"⚠️ {e}\n输入 `@offboarding-bot help` 查看可用命令",
                )
                return

        # 查发送者业务 role（与 webhook 一致）
        async with new_session() as session:
            user_role = await self._resolve_user_role(session, sender_name)
            ctx = BotInvocationContext(
                user_name=sender_name,
                user_id=post_user_id,
                channel_id=channel_id,
                user_role=user_role,
                mm_helpers={
                    "post_channel": self._post_reply,
                    "send_dm": self._send_dm_by_username,
                    "ensure_in_channel": self._ensure_user_in_channel,
                },
            )
            # bot_service 需要 flow_service，复用 deps 构造
            from offboarding_flow.flow_engine.graph import get_graph
            from offboarding_flow.notifications.outbox_repository import OutboxRepository
            from offboarding_flow.services import FlowService, NotificationService
            from offboarding_flow.state_store.repositories import (
                ActionRepository,
                FlowRepository,
                NodeRepository,
            )

            flow_repo = FlowRepository(session)
            node_repo = NodeRepository(session)
            action_repo = ActionRepository(session)
            outbox_repo = OutboxRepository(session)
            notif = NotificationService(
                session=session, outbox_repo=outbox_repo, settings=self.settings
            )
            flow_service = FlowService(
                session, flow_repo, node_repo, action_repo, get_graph(), notification_service=notif
            )
            bot_service = BotService(session=session, flow_service=flow_service)
            try:
                reply = await bot_service.dispatch(cmd, ctx)
            except BotPermissionError as e:
                reply = f"🚫 {e}"
            except BotFlowNotFoundError as e:
                reply = f"⚠️ {e}"
            except Exception as e:
                logger.exception("[mm_listener] dispatch error: %s", e)
                reply = "⚠️ 命令处理失败，请联系管理员"

        await self._post_reply(channel_id, reply)

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
