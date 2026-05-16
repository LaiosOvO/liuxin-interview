"""build_deep_link 单元测试 — query string 格式（R2 方案 A）。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from offboarding_flow.auth import build_deep_link
from tests.auth.factories import JWTPayloadFactory


def test_build_deep_link_basic() -> None:
    """基础 URL 拼接：/flow/handle?flow_id=...&node_id=...&token=..."""
    payload = JWTPayloadFactory.build()
    token = "eyJfake.token.string"
    url = build_deep_link(token, payload, base_url="http://192.168.2.44:3000")
    assert "/flow/handle?" in url
    assert "flow_id=" in url
    assert "node_id=" in url
    assert "token=" in url


def test_build_deep_link_strips_trailing_slash() -> None:
    """base_url 含尾斜杠时不双斜杠。"""
    payload = JWTPayloadFactory.build()
    url1 = build_deep_link("t", payload, base_url="http://x:3000")
    url2 = build_deep_link("t", payload, base_url="http://x:3000/")
    assert url1 == url2


def test_build_deep_link_query_contains_correct_uuid_values() -> None:
    """query string 中 flow_id / node_id 是原 payload UUID 字符串。"""
    payload = JWTPayloadFactory.build()
    url = build_deep_link("tok", payload, base_url="http://x")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert qs["flow_id"] == [str(payload.flow_id)]
    assert qs["node_id"] == [str(payload.node_id)]
    assert qs["token"] == ["tok"]


def test_build_deep_link_path_is_handle() -> None:
    """path 固定为 /flow/handle（R2 方案 A — 单一静态壳页面）。"""
    payload = JWTPayloadFactory.build()
    url = build_deep_link("tok", payload, base_url="http://x:3000")
    parsed = urlparse(url)
    assert parsed.path == "/flow/handle"


def test_build_deep_link_query_has_all_three_keys() -> None:
    """query 必有 flow_id / node_id / token 三个 key（顺序不强制）。"""
    payload = JWTPayloadFactory.build()
    url = build_deep_link("tok", payload, base_url="http://x")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert set(qs.keys()) == {"flow_id", "node_id", "token"}
