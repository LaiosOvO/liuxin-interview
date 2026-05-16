"""auth 测试数据工厂 — polyfactory 生成 JWTPayload / SessionPayload。

约定：
- 固定 sub/email/role/node_name 便于断言可读
- iat/exp/jti 用动态值（每个测试不同）
"""

from __future__ import annotations

import time
import uuid

from polyfactory.factories.pydantic_factory import ModelFactory

from offboarding_flow.auth.schemas import JWTPayload, SessionPayload


class JWTPayloadFactory(ModelFactory[JWTPayload]):
    """JWT deep-link token payload 工厂。"""

    __model__ = JWTPayload

    @classmethod
    def sub(cls) -> str:
        return "li.si"

    @classmethod
    def email(cls) -> str:
        return "li.si@demo.local"

    @classmethod
    def role(cls) -> str:
        return "manager"

    @classmethod
    def node_name(cls) -> str:
        return "manager_review"

    @classmethod
    def allowed_actions(cls) -> list[str]:
        return ["advance", "return", "reject"]

    @classmethod
    def iat(cls) -> int:
        return int(time.time())

    @classmethod
    def exp(cls) -> int:
        return int(time.time()) + 3600

    @classmethod
    def jti(cls) -> str:
        return uuid.uuid4().hex


class SessionPayloadFactory(ModelFactory[SessionPayload]):
    """Session cookie payload 工厂。"""

    __model__ = SessionPayload

    @classmethod
    def sub(cls) -> str:
        return "li.si"

    @classmethod
    def role(cls) -> str:
        return "manager"

    @classmethod
    def exp(cls) -> int:
        return int(time.time()) + 86400
