"""POST /api/auth/exchange — 邮件深链 token 换 HttpOnly cookie。

PRD §6.2.2 锁定 7 步流程；CONTEXT §D8 详细实现。
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from offboarding_flow.api.deps import SessionDep
from offboarding_flow.api.envelope import ok
from offboarding_flow.auth import cookie as cookie_helper
from offboarding_flow.auth import session_service
from offboarding_flow.auth.deps import get_redis_dep
from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class ExchangeRequest(BaseModel):
    """POST /api/auth/exchange body。"""

    token: str = Field(..., min_length=20)  # JWT 最小长度


@router.post("/exchange")
async def exchange(
    body: ExchangeRequest,
    response: Response,
    redis: Annotated[Redis, Depends(get_redis_dep)],
    session: SessionDep,
) -> dict:
    """token 换 cookie。任何失败统一 401 envelope（全局 AuthError handler）。"""
    settings = get_settings()
    result = await session_service.exchange_token(body.token, redis, session)
    cookie_helper.set_session_cookie(response, result.session_token, settings)
    return ok(
        {
            "redirect_to": result.redirect_to,
            "role": result.role,
            "name": result.name,
        }
    )


@router.post("/logout")
async def logout(response: Response) -> dict:
    """清 cookie — 不需要鉴权，前端调即可清空 session。"""
    settings = get_settings()
    cookie_helper.clear_session_cookie(response, settings)
    return ok({"message": "logged out"})
