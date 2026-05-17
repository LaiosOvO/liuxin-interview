"""Huly IMProvider — 通过 httpx 调 huly-bridge sidecar 实现 IMProvider Protocol。

Phase 8 / HULY-06 / Plan 05 Task 3

设计：
- 所有 IM 操作走 sidecar `http://huly-bridge:7777/api/im/*` 路由
- BRIDGE_TOKEN 通过 `X-Bridge-Token` header 注入（NFR-05）
- 与 sidecar 端 src/im.ts 对齐：
  - POST /api/im/send_dm      body {to_username, markdown}
  - POST /api/im/post_channel body {channel_id, markdown}
  - POST /api/im/ensure_member body {channel_id, username}
- ABS-04 register_command_listener — 因为 listener 走独立 huly_listener.py（webhook 模式），
  本 Provider 的 hook 是 no-op + log info

未实现项（Plan 06 补）：
- list_team_users() — 当前返回空列表 + log warning，由 seed_huly_users 离线维护身份映射
- resolve_username() — 返回 demo 域名构造的 UserInfo（仅作为占位）
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from offboarding_flow.config import Settings

from .base import ProviderError, UserInfo

logger = logging.getLogger(__name__)


class HulyIMProvider:
    """Huly 实现的 IMProvider — 通过 HTTP 转发到 huly-bridge sidecar。"""

    name = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.huly_bridge_url.rstrip("/")
        self._token = settings.huly_bridge_token
        self._timeout = settings.huly_bridge_http_timeout
        self._dispatch: Any = None
        if not self._token:
            logger.warning(
                "[huly-im-provider] HULY_BRIDGE_TOKEN 为空 — 所有 sidecar 调用将被 401 拒绝"
            )

    # ------------------------------------------------------------------ #
    # ABS-04 — listener hook（HulyIMProvider 本身不接收 webhook，由 huly_listener.py 承担）
    # ------------------------------------------------------------------ #

    def register_command_listener(self, dispatch: Any) -> None:
        """ABS-04 — HulyIMProvider 仅做 sidecar HTTP 客户端，不主动 invoke dispatch；
        实际 webhook 入口在 api/internal_huly.py → workers/huly_listener.py。

        本方法仅保留 dispatch 引用 + log info（满足 Protocol 契约）。
        """
        self._dispatch = dispatch
        logger.info(
            "[huly-im-provider] register_command_listener: %s (no-op — webhook 走 huly_listener.py)",
            getattr(dispatch, "__name__", "<callable>"),
        )

    # ------------------------------------------------------------------ #
    # 共享 httpx 客户端构造
    # ------------------------------------------------------------------ #

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
                "X-Bridge-Token": self._token,
            },
            timeout=self._timeout,
        )

    @staticmethod
    def _ensure_ok(action: str, response: httpx.Response) -> dict[str, Any]:
        """统一解析 sidecar envelope —— ok=true 取 data；ok=false 抛 ProviderError。"""
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {}
            code = body.get("code", "HTTP_ERROR")
            error = body.get("error", response.text[:200])
            raise ProviderError(f"huly {action} 失败 ({response.status_code} {code}): {error}")
        try:
            payload = response.json()
        except Exception as e:
            raise ProviderError(f"huly {action} 响应非 JSON: {e}") from e
        if not payload.get("ok"):
            raise ProviderError(
                f"huly {action} 失败: {payload.get('error', 'unknown')} "
                f"(code={payload.get('code', 'UNKNOWN')})"
            )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ #
    # IMProvider Protocol — 5 个核心方法
    # ------------------------------------------------------------------ #

    async def send_dm(self, username: str, markdown: str) -> None:
        """私聊推送 — POST /api/im/send_dm。"""
        async with self._client() as c:
            r = await c.post(
                "/api/im/send_dm",
                json={"to_username": username, "markdown": markdown},
            )
        self._ensure_ok("send_dm", r)

    async def post_to_channel(self, channel_id: str, markdown: str) -> None:
        """频道推送 — POST /api/im/post_channel。"""
        async with self._client() as c:
            r = await c.post(
                "/api/im/post_channel",
                json={"channel_id": channel_id, "markdown": markdown},
            )
        self._ensure_ok("post_channel", r)

    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        """成员管理 — POST /api/im/ensure_member。"""
        async with self._client() as c:
            r = await c.post(
                "/api/im/ensure_member",
                json={"channel_id": channel_id, "username": username},
            )
        self._ensure_ok("ensure_member", r)

    async def list_team_users(self) -> list[UserInfo]:
        """列出团队成员 — v1 stub 返回空列表（Plan 06 seed 后补 sidecar /api/im/users 端点）。

        当前 sidecar 不提供该端点 — Plan 06 通过 seed_huly_users.py 离线维护 users 表，
        业务层（FlowService.create_flow_for_user 等）从业务 DB users 表查身份即可。
        """
        logger.warning(
            "[huly-im-provider] list_team_users() v1 返回空列表 — "
            "请通过业务 DB users 表查身份；Plan 06+ 补 sidecar /api/im/users 端点"
        )
        return []

    async def resolve_username(self, username: str) -> UserInfo | None:
        """按 username 查 user info — v1 stub 返回 demo 域名构造的 UserInfo。

        Plan 06 真接入 sidecar /api/im/user 端点后改成真查询。
        """
        if not username:
            return None
        return UserInfo(
            id=f"huly_pending_{username}",
            username=username,
            email=f"{username}@demo.local",
            name=username,
            provider=self.name,
        )
