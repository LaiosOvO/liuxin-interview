"""jwt_service encode/decode 单元测试 — pyjwt round trip + 异常路径。"""

from __future__ import annotations

import time
import uuid

import jwt as pyjwt
import pytest

from offboarding_flow.auth import (
    ExpiredTokenError,
    InvalidTokenError,
    decode,
    decode_session,
    encode,
    encode_session,
)
from offboarding_flow.config import reload_settings
from tests.auth.factories import JWTPayloadFactory


@pytest.fixture(autouse=True)
def _isolate_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试用独立 jwt_secret，避免污染。"""
    monkeypatch.setenv("JWT_SECRET", "test_secret_" + uuid.uuid4().hex)
    monkeypatch.setenv("SESSION_EXPIRY_HOURS", "24")
    reload_settings()
    yield
    reload_settings()


def test_encode_decode_round_trip() -> None:
    """encode → decode 字段一致。"""
    payload = JWTPayloadFactory.build()
    token = encode(payload)
    decoded = decode(token)
    assert decoded.sub == payload.sub
    assert decoded.role == payload.role
    assert decoded.flow_id == payload.flow_id
    assert decoded.node_id == payload.node_id
    assert decoded.jti == payload.jti


def test_decode_expired_token_raises_ExpiredTokenError() -> None:
    """用过去时间签发 → decode 抛 ExpiredTokenError。"""
    past = int(time.time()) - 7200
    payload = JWTPayloadFactory.build(iat=past, exp=past + 60)  # 1 小时前签 + 1 小时已过
    token = encode(payload)
    with pytest.raises(ExpiredTokenError):
        decode(token)


def test_decode_wrong_secret_raises_InvalidTokenError(monkeypatch: pytest.MonkeyPatch) -> None:
    """切换 jwt_secret 后 decode 抛 InvalidTokenError。"""
    payload = JWTPayloadFactory.build()
    token = encode(payload)
    # 换 secret 后 decode
    monkeypatch.setenv("JWT_SECRET", "completely_different_secret_" + uuid.uuid4().hex)
    reload_settings()
    with pytest.raises(InvalidTokenError):
        decode(token)


def test_decode_wrong_algorithm_raises_InvalidTokenError() -> None:
    """HS384 签发的 token 用 HS256 decode → InvalidTokenError。"""
    from offboarding_flow.config import get_settings

    settings = get_settings()
    payload_data = JWTPayloadFactory.build().model_dump(mode="json")
    # 用 HS384 bypass 本模块 encode
    bad_token = pyjwt.encode(payload_data, settings.jwt_secret, algorithm="HS384")
    with pytest.raises(InvalidTokenError):
        decode(bad_token)


def test_decode_missing_required_claim_raises_InvalidTokenError() -> None:
    """手工 encode 缺 jti claim → decode 抛 InvalidTokenError。"""
    from offboarding_flow.config import get_settings

    settings = get_settings()
    incomplete_payload = {
        "sub": "li.si",
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        # 缺 jti
    }
    token = pyjwt.encode(incomplete_payload, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode(token)


def test_decode_malformed_token_raises_InvalidTokenError() -> None:
    """完全不像 jwt 的字符串 → InvalidTokenError。"""
    with pytest.raises(InvalidTokenError):
        decode("not.a.jwt")


def test_decode_invalid_schema_raises_InvalidTokenError() -> None:
    """JWT 有 sub/iat/exp/jti 但缺 flow_id 等 schema 字段 → InvalidTokenError（Pydantic）。"""
    from offboarding_flow.config import get_settings

    settings = get_settings()
    minimal = {
        "sub": "li.si",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": "x" * 12,
        # 缺 email/role/flow_id/node_id/node_name 等
    }
    token = pyjwt.encode(minimal, settings.jwt_secret, algorithm="HS256")
    with pytest.raises(InvalidTokenError):
        decode(token)


def test_encode_session_then_decode_session_round_trip() -> None:
    """encode_session → decode_session 字段一致 + typ='session'。"""
    payload = JWTPayloadFactory.build()
    cookie = encode_session(payload)
    session = decode_session(cookie)
    assert session.sub == payload.sub
    assert session.role == payload.role
    assert session.flow_id == payload.flow_id
    assert session.node_id == payload.node_id
    assert session.typ == "session"
    # session exp 应当大于 token exp（由 settings.session_expiry_hours 决定）
    assert session.exp > int(time.time())
