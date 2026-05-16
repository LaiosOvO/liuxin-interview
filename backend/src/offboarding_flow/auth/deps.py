"""FastAPI Depends 体系 — get_redis_dep + get_current_user + require_role。

约定（CONTEXT §D8）：
- get_current_user 从 cookie 读 session token → decode → 返回 SessionPayload
- require_role(*roles) 工厂返回 Depends，校验 role 在白名单
- 失败统一抛 AuthError（全局 handler 返回 401 envelope）
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import Depends, Request
from redis.asyncio import Redis

from offboarding_flow.config import Settings, get_settings

from . import jwt_service
from .errors import AuthError
from .redis_client import get_redis
from .schemas import SessionPayload

logger = logging.getLogger(__name__)


async def get_redis_dep() -> Redis:
    """FastAPI Depends — 复用 redis_client 单例。"""
    return await get_redis()


async def get_current_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> SessionPayload:
    """从 cookie 取 session token → decode → 返回 payload。

    失败抛 AuthError（统一 401 envelope）。
    """
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        raise AuthError(reason="no_cookie")
    return jwt_service.decode_session(cookie_value)


def require_role(*roles: str) -> Callable:
    """工厂：返回一个 Depends，校验当前 user 角色在 roles 中。"""

    async def _check(user: SessionPayload = Depends(get_current_user)) -> SessionPayload:
        if user.role not in roles:
            logger.warning(
                "[auth.deps] role check fail required=%s actual=%s sub=%s",
                roles,
                user.role,
                user.sub,
            )
            raise AuthError(reason="role_not_allowed")
        return user

    return _check
