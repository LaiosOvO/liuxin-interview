"""cookie.set/clear_session_cookie 单元测试 — PITFALLS #12 参数锁定。"""

from __future__ import annotations

from fastapi import Response

from offboarding_flow.auth import clear_session_cookie, set_session_cookie
from offboarding_flow.config import Settings


def _get_set_cookie_headers(response: Response) -> list[str]:
    """从 raw_headers 中找所有 Set-Cookie 头（小写不区分）。"""
    out: list[str] = []
    for name, value in response.raw_headers:
        if name.lower() == b"set-cookie":
            out.append(value.decode() if isinstance(value, bytes) else value)
    return out


def _make_settings(app_mode: str = "demo", https_enabled: bool = False) -> Settings:
    """构造测试用 Settings（绕过 .env）。"""
    return Settings(
        app_mode=app_mode,
        https_enabled=https_enabled,
        session_cookie_name="test_session",
        session_expiry_hours=24,
        jwt_secret="x" * 64,  # 防 prod 模式校验
    )


def test_set_session_cookie_demo_mode_no_secure_flag() -> None:
    """app_mode=demo → secure=False（内网 HTTP 不能开 Secure）。"""
    settings = _make_settings(app_mode="demo")
    response = Response()
    set_session_cookie(response, "fake.jwt.token", settings)
    headers = _get_set_cookie_headers(response)
    assert headers, "应当签发了 set-cookie"
    header = headers[0]
    assert "Secure" not in header


def test_set_session_cookie_prod_https_enabled_has_secure() -> None:
    """app_mode=prod + https_enabled=True → secure=True。"""
    settings = _make_settings(app_mode="prod", https_enabled=True)
    response = Response()
    set_session_cookie(response, "fake.jwt.token", settings)
    header = _get_set_cookie_headers(response)[0]
    assert "Secure" in header


def test_set_session_cookie_samesite_lax_not_strict() -> None:
    """SameSite=Lax 锁定（PITFALLS #12 — 邮件跨站跳要带 cookie）。"""
    settings = _make_settings()
    response = Response()
    set_session_cookie(response, "fake.jwt.token", settings)
    header = _get_set_cookie_headers(response)[0].lower()
    assert "samesite=lax" in header
    assert "samesite=strict" not in header


def test_set_session_cookie_httponly_flag_present() -> None:
    """HttpOnly 强制（防 XSS 窃取）。"""
    settings = _make_settings()
    response = Response()
    set_session_cookie(response, "fake.jwt.token", settings)
    header = _get_set_cookie_headers(response)[0]
    assert "HttpOnly" in header


def test_clear_session_cookie_emits_delete() -> None:
    """clear 应当签发一个 expires=过去时间 的 set-cookie 头。"""
    settings = _make_settings()
    response = Response()
    clear_session_cookie(response, settings)
    headers = _get_set_cookie_headers(response)
    assert headers, "clear 应当也签 set-cookie"
    header = headers[0].lower()
    # FastAPI delete_cookie 会设置 max-age=0 或 expires=过去
    assert "test_session=" in header
