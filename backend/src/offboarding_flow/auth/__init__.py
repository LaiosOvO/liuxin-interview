"""Phase 3 鉴权模块：JWT 签发/解码 + 深链构造 + jti 一次性消费 + cookie 签发 + role 校验。

Public API：
- 异常体系：AuthError / ExpiredTokenError / InvalidTokenError / TokenAlreadyConsumedError
- Payload schema：JWTPayload / SessionPayload
- JWT 服务：encode / decode / encode_session / decode_session
- 深链构造：build_deep_link
"""

from __future__ import annotations

from .deep_link import build_deep_link
from .errors import (
    AuthError,
    ExpiredTokenError,
    InvalidTokenError,
    TokenAlreadyConsumedError,
)
from .jti_service import (
    consume_jti,
    invalidate_node_tokens,
    is_jti_consumed,
    register_node_token,
)
from .jwt_service import decode, decode_session, encode, encode_session
from .redis_client import dispose_redis, get_redis
from .schemas import JWTPayload, SessionPayload

__all__ = [
    # errors
    "AuthError",
    "ExpiredTokenError",
    "InvalidTokenError",
    "TokenAlreadyConsumedError",
    # schemas
    "JWTPayload",
    "SessionPayload",
    # jwt service
    "encode",
    "decode",
    "encode_session",
    "decode_session",
    # deep link
    "build_deep_link",
    # redis / jti
    "get_redis",
    "dispose_redis",
    "consume_jti",
    "is_jti_consumed",
    "register_node_token",
    "invalidate_node_tokens",
]
