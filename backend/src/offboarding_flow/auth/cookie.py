"""Session cookie 签发/清理 — PITFALLS #12 锁定参数。

约定：
- SameSite=Lax 不能 Strict（邮件跨站跳会丢 cookie）
- secure 仅生产 HTTPS 才开（内网 HTTP 部署关）
- HttpOnly 强制（防 XSS 窃取）
"""

from __future__ import annotations

from fastapi import Response

from offboarding_flow.config import Settings


def set_session_cookie(response: Response, session_token: str, settings: Settings) -> None:
    """签发 HttpOnly + SameSite=Lax cookie。"""
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        httponly=True,
        secure=(settings.app_mode == "prod" and settings.https_enabled),
        samesite="lax",
        max_age=settings.session_expiry_hours * 3600,
        path="/",
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    """清除 cookie — 同 key/path 参数。"""
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
    )
