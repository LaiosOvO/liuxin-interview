"""HulyListener — IMListener Protocol 实现（Phase 8 B-full 重构）。

去 sidecar 后没有反向 webhook 入口。当前 v1 实现：
- start / stop / register_command_listener 是 no-op + log
- bot @ 命令未启用（user 通过 Huly UI @bot 暂时不会触发流程）

后续如需 bot @ 反向触发，加 polling 模式：每 10s 查询 bot 关注的所有 dm-* channel 的
新 ChatMessage，调 dispatch。本 v1 优先确保 IM 推送 + Doc 创建 work。

对照 MattermostListener：
- MM 走 WebSocket 长连 — 主动接事件
- Huly v1 暂无长连（REST polling 占位）— 不影响出站消息
"""

from __future__ import annotations

import logging
from typing import Any

from offboarding_flow.config import Settings
from offboarding_flow.im.protocol import DispatchFn

logger = logging.getLogger(__name__)


class HulyListener:
    """Huly 平台 listener — v1 占位（IM 推送通过 HulyIMProvider 即可，无需 listener）。"""

    name: str = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._dispatch: DispatchFn | None = None

    async def start(self) -> None:
        logger.info(
            "[huly_listener] 启动（v1 stub — 出站消息走 HulyIMProvider；"
            "bot @ 反向触发暂未实现，后续补 polling 模式）"
        )

    async def stop(self) -> None:
        logger.info("[huly_listener] 停止（v1 stub 无长连接）")

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        self._dispatch = dispatch
        logger.info(
            "[huly_listener] dispatch listener registered: %s (v1 暂不主动 invoke)",
            getattr(dispatch, "__name__", "<callable>"),
        )

    async def handle_webhook(self, event: dict[str, Any]) -> None:
        """兼容旧 internal_huly 路由（如果仍 mounted）— v1 stub 仅 log。"""
        logger.warning(
            "[huly_listener] handle_webhook 收到事件但 v1 已无 sidecar webhook 路径，丢弃 event=%s",
            str(event.get("message", ""))[:80],
        )
