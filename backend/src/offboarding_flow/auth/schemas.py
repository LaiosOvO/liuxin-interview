"""auth payload schema — PRD §6.2.1 锁定。

约定（CONTEXT §D4）：
- Pydantic v2，extra="forbid" 防 token 走样
- JWTPayload 是深链 token 的完整 body；SessionPayload 是 cookie 精简版（typ='session' 区分）
- 所有字段强类型，flow_id/node_id 用 UUID（json 序列化为 str）
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class JWTPayload(BaseModel):
    """deep-link token payload — JWT body（PRD §6.2.1 锁定字段集）。"""

    model_config = ConfigDict(extra="forbid")

    sub: str = Field(..., min_length=1)  # 操作人 username
    email: str
    role: str  # employee / manager / hr / it_admin / finance / legal
    flow_id: UUID
    node_id: UUID
    node_name: str
    allowed_actions: list[str] = Field(default_factory=list)
    iat: int  # unix ts (issued at)
    exp: int  # unix ts (expires at)
    jti: str = Field(..., min_length=8)  # 一次性 uuid hex


class SessionPayload(BaseModel):
    """session cookie payload — 比 token 精简（不带 jti / allowed_actions / iat）。"""

    model_config = ConfigDict(extra="forbid")

    sub: str
    role: str
    flow_id: UUID
    node_id: UUID
    exp: int
    typ: str = "session"  # 区分 token vs session（防 token 被当 cookie 用）
