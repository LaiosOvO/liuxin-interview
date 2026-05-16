"""JWT 签发与解码 — HS256 + JWT_SECRET（仅 env 注入）。

约定（CONTEXT §D4）：
- HS256 算法（pyjwt[crypto]，不用 python-jose — 已 deprecated，SUMMARY R3）
- decode 严格校验签名 + exp + 必需字段；leeway=0 严格 exp
- 对外异常用 auth.errors 体系（不暴露 pyjwt 内部异常类型）
- encode_session 从 token payload 派生 session cookie 值（typ='session' 区分）
"""

from __future__ import annotations

import time
from typing import Any

import jwt as pyjwt  # pyjwt 包名 jwt，alias 防与本模块冲突
from pydantic import ValidationError

from offboarding_flow.config import get_settings

from .errors import ExpiredTokenError, InvalidTokenError
from .schemas import JWTPayload, SessionPayload

_ALG = "HS256"


def encode(payload: JWTPayload) -> str:
    """签发 token（HS256 + JWT_SECRET）。payload.iat/exp/jti 必须由调用方填写。"""
    settings = get_settings()
    data = payload.model_dump(mode="json")
    return pyjwt.encode(data, settings.jwt_secret, algorithm=_ALG)


def decode(token: str) -> JWTPayload:
    """解码 + 验签 + Pydantic 校验。失败抛 AuthError 子类。"""
    settings = get_settings()
    try:
        raw: dict[str, Any] = pyjwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALG],
            options={"require": ["exp", "iat", "jti", "sub"]},
            leeway=0,
        )
    except pyjwt.ExpiredSignatureError as e:
        raise ExpiredTokenError("token 已过期") from e
    except pyjwt.InvalidTokenError as e:
        raise InvalidTokenError("token 无效") from e

    try:
        return JWTPayload.model_validate(raw)
    except ValidationError as e:
        raise InvalidTokenError("token payload schema 不匹配") from e


def encode_session(token_payload: JWTPayload) -> str:
    """从 token payload 派生 session cookie JWT。TTL 由 settings.session_expiry_hours 决定。"""
    settings = get_settings()
    exp = int(time.time()) + settings.session_expiry_hours * 3600
    session = SessionPayload(
        sub=token_payload.sub,
        role=token_payload.role,
        flow_id=token_payload.flow_id,
        node_id=token_payload.node_id,
        exp=exp,
    )
    return pyjwt.encode(
        session.model_dump(mode="json"),
        settings.jwt_secret,
        algorithm=_ALG,
    )


def decode_session(cookie_value: str) -> SessionPayload:
    """解码 session cookie。失败抛 AuthError 子类。"""
    settings = get_settings()
    try:
        raw = pyjwt.decode(
            cookie_value,
            settings.jwt_secret,
            algorithms=[_ALG],
            options={"require": ["exp", "sub"]},
            leeway=0,
        )
    except pyjwt.ExpiredSignatureError as e:
        raise ExpiredTokenError("session 已过期") from e
    except pyjwt.InvalidTokenError as e:
        raise InvalidTokenError("session 无效") from e

    try:
        return SessionPayload.model_validate(raw)
    except ValidationError as e:
        raise InvalidTokenError("session payload schema 不匹配") from e
