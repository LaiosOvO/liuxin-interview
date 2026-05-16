"""auth 模块异常体系。

约定（CONTEXT §D12）：
- 对外统一 401 + 中文 detail "鉴权失败"（不泄露具体原因）
- 内部 reason 字段供 structlog 写日志便于排查
- 子类化方便 except 时区分（生产代码主要 except AuthError 父类即可）
"""

from __future__ import annotations


class AuthError(Exception):
    """鉴权失败基类 — 默认 401 + 通用 detail，子类覆盖 reason。"""

    status_code: int = 401
    reason: str = "auth_failed"
    detail: str = "鉴权失败"

    def __init__(self, detail: str | None = None, *, reason: str | None = None) -> None:
        super().__init__(detail or self.detail)
        if detail:
            self.detail = detail
        if reason:
            self.reason = reason


class ExpiredTokenError(AuthError):
    """JWT 已过期。"""

    reason = "token_expired"


class InvalidTokenError(AuthError):
    """JWT 签名错 / 字段缺失 / payload schema 不匹配。"""

    reason = "token_invalid"


class TokenAlreadyConsumedError(AuthError):
    """jti 已被消费（双击 race / 重放攻击）。"""

    reason = "jti_replay"
