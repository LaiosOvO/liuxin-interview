"""Mattermost 出站发送器（NOTI-02 — PRD §7.2 + §16.3）。

职责：
- 使用 Bot Personal Access Token 调用 POST /api/v4/posts 推送消息
- 支持 plain text + Interactive Message attachments（fields / actions / title_link）
- 跳转 URL 用 auth.deep_link.build_deep_link 生成（一键登录）

约定（CLAUDE.md §3.5 凭证安全 + §6 中文化）：
- Bot Token 从 Settings 注入，不写死
- 用户面向文本（attachment 标题 / 字段 label）必须中文
- 调用方控制是否入 outbox（Slice 4B 不直接入；Slice 4D 由 outbox_drain 调用）
- httpx.AsyncClient 复用 connection；调用方负责生命周期（DI 模式）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from offboarding_flow.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常 / DTO
# ---------------------------------------------------------------------------
class MattermostSendError(Exception):
    """Mattermost 调用失败 — 调用方决定重试 / 入 outbox 失败队列。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class MattermostMessage:
    """出站消息 DTO（immutability — CLAUDE.md / 全局 coding-style）。

    channel_id: 目标频道 ID（不是 channel name；Mattermost API 用 ID）
    message: 主文本（markdown 支持）
    attachments: Interactive Message 卡片列表（PRD §7.2 JSON 格式）
    """

    channel_id: str
    message: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)


def build_action_attachment(
    *,
    title: str,
    title_link: str | None,
    text: str,
    color: str = "#FFA500",
    fields: list[dict[str, Any]] | None = None,
    actions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构造一个 Interactive Message attachment（PRD §7.2 JSON 样板）。

    Args:
        title: 卡片标题（如 "李四 - 设备归还"）
        title_link: 标题点击跳转 URL（一键登录深链；None 表示无链接）
        text: 描述正文
        color: 卡片左侧色条（默认橙色 = 待处理）
        fields: 结构化字段列表 [{"title": "员工", "value": "李四", "short": True}, ...]
        actions: 按钮列表 [{"name": "继续", "integration": {"url": "..."}}, ...]

    Returns:
        attachment dict — 可直接放进 MattermostMessage.attachments
    """
    attachment: dict[str, Any] = {
        "title": title,
        "text": text,
        "color": color,
    }
    if title_link:
        attachment["title_link"] = title_link
    if fields:
        attachment["fields"] = fields
    if actions:
        attachment["actions"] = actions
    return attachment


# ---------------------------------------------------------------------------
# Sender
# ---------------------------------------------------------------------------
class MattermostSender:
    """Mattermost API 客户端封装（PAT 调 /api/v4/posts）。

    单例 / DI 友好：调用方传入 httpx.AsyncClient（复用连接池）。
    若调用方不传，sender 内部建一个 short-lived client（不推荐生产用，方便测试）。
    """

    def __init__(
        self,
        settings: Settings,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> MattermostSender:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._settings.mattermost_http_timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._settings.mattermost_bot_token}",
            "Content-Type": "application/json",
        }

    @property
    def _posts_url(self) -> str:
        return f"{self._settings.mattermost_url.rstrip('/')}/api/v4/posts"

    async def post(self, msg: MattermostMessage) -> dict[str, Any]:
        """推送一条消息到 Mattermost 频道。

        Args:
            msg: MattermostMessage DTO

        Returns:
            Mattermost API 返回的 post JSON（含 id / create_at 等）

        Raises:
            MattermostSendError: 网络失败 / 4xx / 5xx
        """
        if not msg.channel_id:
            raise MattermostSendError("channel_id 不能为空", status_code=None)

        if self._client is None:
            # 容错：调用方没 enter context manager — 建临时 client
            self._client = httpx.AsyncClient(timeout=self._settings.mattermost_http_timeout)
            self._owns_client = True

        payload: dict[str, Any] = {
            "channel_id": msg.channel_id,
            "message": msg.message,
        }
        if msg.attachments:
            # Mattermost: attachments 必须放进 props.attachments
            payload["props"] = {"attachments": msg.attachments}

        try:
            response = await self._client.post(
                self._posts_url,
                json=payload,
                headers=self._headers,
            )
        except httpx.RequestError as e:
            logger.exception("[mattermost_sender] httpx 网络错误: %s", e)
            raise MattermostSendError(f"网络错误: {e}", status_code=None) from e

        if response.status_code >= 400:
            logger.warning(
                "[mattermost_sender] Mattermost 拒绝 status=%s body=%s",
                response.status_code,
                response.text[:200],
            )
            raise MattermostSendError(
                f"Mattermost API 返回 {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

        logger.info(
            "[mattermost_sender] post ok channel=%s len=%d",
            msg.channel_id,
            len(msg.message),
        )
        return response.json()

    async def reply_text(self, channel_id: str, text: str) -> dict[str, Any]:
        """便捷方法：纯文本回复（bot_service 8 命令大量用）。"""
        return await self.post(MattermostMessage(channel_id=channel_id, message=text))
