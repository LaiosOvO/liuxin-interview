"""role_router.resolve_redirect 单元测试。"""

from __future__ import annotations

import uuid

import pytest

from offboarding_flow.auth import resolve_redirect


@pytest.mark.parametrize(
    "role,expected_segment",
    [
        ("applicant", "/applicant"),
        ("manager", "/manager"),
        ("hr", "/hr"),
        ("it_admin", "/it"),
        ("finance", "/finance"),
        ("legal", "/legal"),
    ],
)
def test_resolve_redirect_for_known_roles(role: str, expected_segment: str) -> None:
    """6 个已知 role 各自有对应 redirect 路径。"""
    flow_id = uuid.uuid4()
    node_id = uuid.uuid4()
    url = resolve_redirect(role, flow_id, node_id)
    assert url.endswith(expected_segment)
    assert str(flow_id) in url
    # applicant 路径不含 node_id（按 PRD §6.2.4 applicant 是全局视图）
    if role != "applicant":
        assert str(node_id) in url


def test_resolve_redirect_unknown_role_fallback_to_applicant() -> None:
    """未知 role 回退到 applicant 视图（safest fallback）。"""
    flow_id = uuid.uuid4()
    node_id = uuid.uuid4()
    url = resolve_redirect("unknown_role_xyz", flow_id, node_id)
    assert url.endswith("/applicant")
    assert str(flow_id) in url


def test_resolve_redirect_starts_with_slash_flow() -> None:
    """所有 redirect 路径以 /flow/ 开头（前端 SPA 路由统一前缀）。"""
    flow_id = uuid.uuid4()
    node_id = uuid.uuid4()
    for role in ["manager", "hr", "it_admin", "finance", "legal", "applicant"]:
        url = resolve_redirect(role, flow_id, node_id)
        assert url.startswith("/flow/"), f"role={role} url={url}"
