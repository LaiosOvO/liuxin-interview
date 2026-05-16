"""JWTPayload / SessionPayload Pydantic schema 单元测试。"""

from __future__ import annotations

import time
import uuid

import pytest
from pydantic import ValidationError

from offboarding_flow.auth.schemas import JWTPayload, SessionPayload


def _full_payload_data() -> dict:
    return {
        "sub": "li.si",
        "email": "li.si@demo.local",
        "role": "manager",
        "flow_id": str(uuid.uuid4()),
        "node_id": str(uuid.uuid4()),
        "node_name": "manager_review",
        "allowed_actions": ["advance", "return", "reject"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
        "jti": uuid.uuid4().hex,
    }


def test_jwt_payload_full_fields_ok() -> None:
    """所有字段齐全 model_validate 通过。"""
    payload = JWTPayload.model_validate(_full_payload_data())
    assert payload.sub == "li.si"
    assert payload.role == "manager"
    assert isinstance(payload.flow_id, uuid.UUID)
    assert len(payload.jti) >= 8


@pytest.mark.parametrize("missing_field", ["sub", "email", "role", "flow_id", "node_id", "jti"])
def test_jwt_payload_missing_required_field_raises(missing_field: str) -> None:
    """缺任一必需字段抛 ValidationError。"""
    data = _full_payload_data()
    del data[missing_field]
    with pytest.raises(ValidationError):
        JWTPayload.model_validate(data)


def test_jwt_payload_extra_fields_rejected() -> None:
    """extra='forbid' — 多余字段抛 ValidationError（防 token 走样）。"""
    data = _full_payload_data()
    data["unknown_field"] = "evil"
    with pytest.raises(ValidationError):
        JWTPayload.model_validate(data)


def test_session_payload_typ_defaults_to_session() -> None:
    """SessionPayload 的 typ 默认 'session'，区分 JWT 主 token。"""
    payload = SessionPayload.model_validate(
        {
            "sub": "li.si",
            "role": "manager",
            "flow_id": str(uuid.uuid4()),
            "node_id": str(uuid.uuid4()),
            "exp": int(time.time()) + 86400,
        }
    )
    assert payload.typ == "session"


def test_jwt_payload_empty_jti_rejected() -> None:
    """jti 最小长度 8 — 太短的 jti 抛 ValidationError。"""
    data = _full_payload_data()
    data["jti"] = "ab"
    with pytest.raises(ValidationError):
        JWTPayload.model_validate(data)


def test_session_payload_extra_fields_rejected() -> None:
    """SessionPayload 也 extra='forbid'。"""
    data = {
        "sub": "li.si",
        "role": "manager",
        "flow_id": str(uuid.uuid4()),
        "node_id": str(uuid.uuid4()),
        "exp": int(time.time()) + 86400,
        "leaked_attr": "X",
    }
    with pytest.raises(ValidationError):
        SessionPayload.model_validate(data)
