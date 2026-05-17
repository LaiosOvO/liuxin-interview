"""Mattermost IMProvider — 用 bot token 调 MM REST API。"""

from __future__ import annotations

import logging

import httpx

from offboarding_flow.config import get_settings

from .base import ProviderError, UserInfo

logger = logging.getLogger(__name__)


class MattermostProvider:
    """Mattermost 实现的 IMProvider。"""

    name = "mattermost"

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = self._settings.mattermost_url.rstrip("/")
        self._bot_token = self._settings.mattermost_bot_token
        self._bot_user_id = self._settings.mattermost_bot_user_id
        # ABS-04 — Phase 08-01 引入；Mattermost listener 走 workers/mattermost_listener.py
        # 这里 Provider 仅用于 REST 推送 / 查询，不接收平台推送，register hook 是 no-op
        self._dispatch = None

    def register_command_listener(self, dispatch) -> None:
        """ABS-04 — MattermostProvider 仅做 REST 客户端，长连接 listener 在
        workers/mattermost_listener.py 单独承担；此 hook 仅保留 dispatch 引用，
        本 Provider 不主动 invoke。
        """
        self._dispatch = dispatch

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._bot_token}",
                "Content-Type": "application/json",
            },
            timeout=self._settings.mattermost_http_timeout,
        )

    async def post_to_channel(self, channel_id: str, markdown: str) -> None:
        async with self._client() as c:
            r = await c.post(
                "/api/v4/posts",
                json={"channel_id": channel_id, "message": markdown},
            )
        if r.status_code >= 400:
            raise ProviderError(f"mm post_to_channel: {r.status_code} {r.text[:200]}")

    async def send_dm(self, username: str, markdown: str) -> None:
        async with self._client() as c:
            user_resp = await c.get(f"/api/v4/users/username/{username}")
            if user_resp.status_code >= 400:
                raise ProviderError(f"mm send_dm user lookup {username}: {user_resp.status_code}")
            target_id = user_resp.json()["id"]
            dm_resp = await c.post(
                "/api/v4/channels/direct",
                json=[self._bot_user_id, target_id],
            )
            if dm_resp.status_code >= 400:
                raise ProviderError(f"mm send_dm create channel: {dm_resp.status_code}")
            channel_id = dm_resp.json()["id"]
            post_resp = await c.post(
                "/api/v4/posts",
                json={"channel_id": channel_id, "message": markdown},
            )
        if post_resp.status_code >= 400:
            raise ProviderError(f"mm send_dm post: {post_resp.status_code} {post_resp.text[:200]}")

    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        async with self._client() as c:
            user_resp = await c.get(f"/api/v4/users/username/{username}")
            if user_resp.status_code >= 400:
                return
            user_id = user_resp.json()["id"]
            await c.post(
                f"/api/v4/channels/{channel_id}/members",
                json={"user_id": user_id},
            )  # 已是成员会 400，忽略

    async def list_team_users(self) -> list[UserInfo]:
        async with self._client() as c:
            t = await c.get(f"/api/v4/teams/name/{self._settings.mattermost_team}")
            t.raise_for_status()
            team_id = t.json()["id"]
            u = await c.get("/api/v4/users", params={"in_team": team_id, "per_page": 100})
            u.raise_for_status()
        results: list[UserInfo] = []
        for mu in u.json():
            if mu.get("is_bot"):
                continue
            results.append(
                UserInfo(
                    id=mu["id"],
                    username=mu.get("username", ""),
                    email=(mu.get("email") or "").lower(),
                    name=mu.get("nickname") or mu.get("username", ""),
                    provider=self.name,
                )
            )
        return results

    async def resolve_username(self, username: str) -> UserInfo | None:
        async with self._client() as c:
            r = await c.get(f"/api/v4/users/username/{username}")
        if r.status_code >= 400:
            return None
        mu = r.json()
        return UserInfo(
            id=mu["id"],
            username=mu.get("username", ""),
            email=(mu.get("email") or "").lower(),
            name=mu.get("nickname") or mu.get("username", ""),
            provider=self.name,
        )
