"""HulyListener — 实现 IMListener Protocol（HULY-07 / Plan 05 Task 3）。

设计：
- sidecar 是独立容器，本 listener 不主动 connect Huly；只承担"接收 sidecar 反向 webhook → 调
  dispatch_message"的转发角色。
- start / stop 是 no-op（webhook 入口由 api/internal_huly.py 的 FastAPI 路由提供）
- handle_webhook 由 internal_huly 路由调用，把 sidecar 推过来的 chat 事件转化成
  dispatch_message 调用（与 MattermostListener._handle_event 同语义）

与 MattermostListener 对比：
- MM listener 主动开 WebSocket 长连 → 接收事件
- Huly listener 被动接收 sidecar HTTP POST → 调 dispatch
- 两者都遵守 IMListener Protocol（name/start/stop/register_command_listener）
"""

from __future__ import annotations

import logging
from typing import Any

from offboarding_flow.config import Settings
from offboarding_flow.im.context import IMHelpers
from offboarding_flow.im.protocol import DispatchFn

logger = logging.getLogger(__name__)


class HulyListener:
    """Huly 平台 listener — 承担反向 webhook → dispatch 转发。

    实现 `offboarding_flow.im.protocol.IMListener` Protocol。
    """

    name: str = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dispatch: DispatchFn | None = None

    # ------------------------------------------------------------------ #
    # IMListener Protocol — 4 个成员
    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        """启动 — Huly listener 走 webhook 模式，本方法只 log 状态。"""
        logger.info(
            "[huly_listener] 启动（webhook 模式，依赖 sidecar POST /api/internal/huly/event 反向推送）"
        )

    async def stop(self) -> None:
        """停止 — webhook 模式无长连接可关，仅 log。"""
        logger.info("[huly_listener] 停止（webhook 模式无连接需断开）")

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        """ABS-04 — 由 main.py lifespan 注入 dispatch_message。"""
        self._dispatch = dispatch
        logger.info(
            "[huly_listener] dispatch listener registered: %s",
            getattr(dispatch, "__name__", "<callable>"),
        )

    # ------------------------------------------------------------------ #
    # 自定义 — webhook 处理（被 api/internal_huly.py 调用）
    # ------------------------------------------------------------------ #

    async def handle_webhook(self, event: dict[str, Any]) -> None:
        """处理 sidecar 反向推送的单条 chat 事件。

        event 字段（与 sidecar src/types.ts ChatEventPayload 对齐 + 加 channel_type）:
            sender_account: str         Huly AccountUuid (modifiedBy)
            sender_username: str | None  反查得到的业务 username
            channel_id: str             dm/channel _id
            channel_type: str           'D'/'O'/'P'（MM 约定）
            attached_to_class: str      Huly 端 class id
            message: str                markdown 文本
            ts: int                     创建时间（ms epoch）

        若 dispatch 未注册 → log warning + 丢弃；不抛。
        若 sender_username 缺 → 用 sender_account 兜底（业务侧无 user 记录会被 dispatcher 转入 LLM 路由）。
        """
        if self._dispatch is None:
            logger.warning(
                "[huly_listener] dispatch 未注册，丢消息：%s",
                str(event.get("message", ""))[:80],
            )
            return

        sender_username = event.get("sender_username")
        if not sender_username:
            # 兜底用 sender_account UUID 作为标识（dispatcher 内 _resolve_user_role 会返回 None）
            sender_username = str(event.get("sender_account", "unknown"))

        sender_account = str(event.get("sender_account", ""))
        channel_id = str(event.get("channel_id", ""))
        channel_type = str(event.get("channel_type", "D"))
        message = str(event.get("message", ""))

        if not message.strip():
            logger.debug("[huly_listener] 空消息（已过滤），sender=%s", sender_username)
            return

        # 构造 IMHelpers — 用 huly_im_provider 的 send_dm / post_to_channel
        # 懒 import 避免启动期循环依赖
        from offboarding_flow.providers.factory import get_im_provider
        from offboarding_flow.state_store.session import new_session

        im = get_im_provider()
        helpers = IMHelpers(
            post_channel=im.post_to_channel,
            send_dm=im.send_dm,
            ensure_in_channel=im.ensure_user_in_channel,
        )

        logger.info(
            "[huly_listener] handling msg from=%s channel=%s channel_type=%s text=%r",
            sender_username,
            channel_id[:8],
            channel_type,
            message[:80],
        )

        await self._dispatch(
            sender_username=sender_username,
            user_id=sender_account,
            channel_id=channel_id,
            channel_type=channel_type,
            message=message,
            im_helpers=helpers,
            settings=self._settings,
            session_factory=new_session,
        )
