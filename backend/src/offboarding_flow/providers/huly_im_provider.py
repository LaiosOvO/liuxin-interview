"""Huly IMProvider — Python 直连 REST 实现（Phase 8 B-full 重构，去 sidecar）。

设计要点（B-full-channel）：
- DM 降级为「每员工一个 chunter:Channel」(bot + employee + 相关 hr 是 members)
  原因：新建 DM 后立即 add ChatMessage 在 server 端有 ACL/join 同步问题（spike 验证）
  Channel 模式 server 立即接受 ChatMessage 写入
- send_dm(username, markdown):
    1. ensure_user_channel(username) → 返回 channel_id（按需创建）
    2. add_collection(ChatMessage, channel_id, ...) → 写入
- post_to_channel(channel_id, markdown):
    直接 add_collection(ChatMessage, channel_id, ...)
- ensure_user_in_channel(channel_id, username):
    find_one(Channel _id=channel_id) → 检查 members → updateDoc $push members 若缺
- list_team_users / resolve_username:
    从业务 DB users 表自己取（Provider 不查 Huly Person — 解耦）

连接管理：
- Lazy connect on first call — 避免 module import 时阻塞
- 单例 PlatformClient 跨调用复用（每 Provider 实例 1 个 client）
- 失败抛 ProviderError，调用方负责重连
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from offboarding_flow.config import Settings

from .base import ProviderError, UserInfo
from .huly import (
    CHUNTER_CLASS_CHANNEL,
    CHUNTER_CLASS_CHAT_MESSAGE,
    CORE_SPACE_SPACE,
    DEMO_EMAIL_DOMAIN,
    HulyPlatformClient,
    connect_huly,
)

logger = logging.getLogger(__name__)


class HulyIMProvider:
    """Huly 实现的 IMProvider — Python REST 直连，无 sidecar。"""

    name = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: HulyPlatformClient | None = None
        self._connect_lock = asyncio.Lock()
        self._dispatch: Any = None
        self._channel_prefix = settings.huly_user_channel_prefix or "dm-"

    # ------------------------------------------------------------------ #
    # ABS-04 listener hook — 不主动 invoke dispatch（由 huly_listener.py 承担）
    # ------------------------------------------------------------------ #

    def register_command_listener(self, dispatch: Any) -> None:
        self._dispatch = dispatch
        logger.info(
            "[huly-im] register_command_listener: %s (Provider 仅做 REST 推送，listener 走 polling)",
            getattr(dispatch, "__name__", "<callable>"),
        )

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    async def _ensure_client(self) -> HulyPlatformClient:
        if self._client is not None:
            return self._client
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            s = self._settings
            if not s.huly_admin_email or not s.huly_admin_password:
                raise ProviderError(
                    "Huly admin 凭证未配置 — 检查 HULY_ADMIN_EMAIL / HULY_ADMIN_PASSWORD"
                )
            try:
                self._client = await connect_huly(
                    accounts_url=s.huly_accounts_url,
                    admin_email=s.huly_admin_email,
                    admin_password=s.huly_admin_password,
                    workspace_url=s.huly_workspace,
                    timeout=s.huly_http_timeout,
                )
            except Exception as e:
                raise ProviderError(f"connect_huly 失败: {e}") from e
            assert self._client is not None
            return self._client

    # ------------------------------------------------------------------ #
    # IMProvider Protocol — 5 个核心方法
    # ------------------------------------------------------------------ #

    async def send_dm(self, username: str, markdown: str) -> None:
        """私聊推送（B-full-channel 模式）— 每员工一个 chunter:Channel。

        步骤：
        1. ensure_user_channel(username) → channel_id（按需创建）
        2. add_collection ChatMessage 到该 Channel 的 messages
        """
        pc = await self._ensure_client()
        channel_id = await self._ensure_user_channel(pc, username)
        try:
            await pc.ops.add_collection(
                CHUNTER_CLASS_CHAT_MESSAGE,
                channel_id,
                channel_id,
                CHUNTER_CLASS_CHANNEL,
                "messages",
                {"message": markdown, "attachments": 0},
            )
        except Exception as e:
            raise ProviderError(f"huly send_dm to {username} 失败: {e}") from e

    async def post_to_channel(self, channel_id: str, markdown: str) -> None:
        """频道推送 — add_collection ChatMessage。"""
        pc = await self._ensure_client()
        try:
            await pc.ops.add_collection(
                CHUNTER_CLASS_CHAT_MESSAGE,
                channel_id,
                channel_id,
                CHUNTER_CLASS_CHANNEL,
                "messages",
                {"message": markdown, "attachments": 0},
            )
        except Exception as e:
            raise ProviderError(f"huly post_to_channel {channel_id[:8]} 失败: {e}") from e

    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        """把 user 加入 chunter:Channel members（已是 member 幂等）。"""
        pc = await self._ensure_client()
        target_uuid = await self._resolve_account(pc, username)
        if target_uuid is None:
            raise ProviderError(f"huly ensure_user_in_channel: 未找到 username={username} 的账号")
        ch = await pc.rest.find_one(CHUNTER_CLASS_CHANNEL, {"_id": channel_id})
        if ch is None:
            raise ProviderError(f"huly ensure_user_in_channel: 未找到 channel={channel_id}")
        members = ch.get("members") or []
        if not isinstance(members, list):
            members = []
        if target_uuid in members:
            return  # 幂等
        try:
            await pc.ops.update_doc(
                CHUNTER_CLASS_CHANNEL,
                CORE_SPACE_SPACE,
                channel_id,
                {"$push": {"members": target_uuid}},
            )
        except Exception as e:
            raise ProviderError(f"huly add members 失败 ({channel_id[:8]}, {username}): {e}") from e

    async def list_team_users(self) -> list[UserInfo]:
        """v1：业务 DB users 表是 source of truth，不查 Huly Person。"""
        logger.debug(
            "[huly-im] list_team_users() 返回 [] — 业务侧请查 DB users 表（与 sidecar 时代一致）"
        )
        return []

    async def resolve_username(self, username: str) -> UserInfo | None:
        """按 username 返回占位 UserInfo（业务侧 DB 才是真实 user 来源）。"""
        if not username:
            return None
        return UserInfo(
            id=f"huly_pending_{username}",
            username=username,
            email=f"{username}@{DEMO_EMAIL_DOMAIN}",
            name=username,
            provider=self.name,
        )

    # ------------------------------------------------------------------ #
    # 内部 helper — Channel-per-user 管理 + 账号解析
    # ------------------------------------------------------------------ #

    async def _resolve_account(self, pc: HulyPlatformClient, username: str) -> str | None:
        """按 username 找 PersonUuid (= AccountUuid)。

        与 sidecar im.ts:resolveAccountByUsername 同语义：
        1. find_one SocialIdentity by key 'email:{username}@demo.local' → attachedTo (PersonId)
        2. find_one Employee mixin by _id=PersonId → personUuid
        """
        social_key = f"email:{username}@{DEMO_EMAIL_DOMAIN}"
        si = await pc.rest.find_one("contact:class:SocialIdentity", {"key": social_key})
        if not si:
            return None
        attached_to = si.get("attachedTo")
        if not attached_to:
            return None
        # 通过 Employee mixin 拿 personUuid
        emp = await pc.rest.find_one("contact:mixin:Employee", {"_id": attached_to})
        if not emp:
            return None
        person_uuid = emp.get("personUuid")
        return str(person_uuid) if person_uuid else None

    async def _ensure_user_channel(self, pc: HulyPlatformClient, username: str) -> str:
        """每员工一个 chunter:Channel — name=`dm-{username}`，members=[bot, employee]。

        返回 channel_id。已存在则复用。
        """
        channel_name = f"{self._channel_prefix}{username}"
        # 查 Channel by name
        ch = await pc.rest.find_one(CHUNTER_CLASS_CHANNEL, {"name": channel_name})
        if ch is not None:
            return str(ch["_id"])
        # 不存在 → 创建
        bot = pc.bot_account
        target = await self._resolve_account(pc, username)
        members = [bot]
        if target:
            members.append(target)
        else:
            logger.warning(
                "[huly-im] _ensure_user_channel: username=%s 无对应 Huly 账号；"
                "channel 仅 bot 是 member（消息仍可发但用户看不到）",
                username,
            )
        try:
            channel_id = await pc.ops.create_doc(
                CHUNTER_CLASS_CHANNEL,
                CORE_SPACE_SPACE,
                {
                    "name": channel_name,
                    "description": f"离职流程私聊频道 — {username}",
                    "topic": "",
                    "private": True,
                    "archived": False,
                    "members": members,
                    "autoJoin": False,
                },
            )
            logger.info(
                "[huly-im] 创建 user channel: name=%s id=%s members=%d",
                channel_name,
                channel_id,
                len(members),
            )
            return channel_id
        except Exception as e:
            raise ProviderError(f"huly create user channel {channel_name} 失败: {e}") from e
