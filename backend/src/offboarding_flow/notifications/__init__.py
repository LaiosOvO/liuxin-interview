"""notifications 子包 — 邮件 outbox + SMTP + 演示模式信封覆写 + 模板渲染。

Phase 4 Slice 4A 落地范围（REQ-NOTI-01 / NOTI-03 / NOTI-04）：
- OutboxRepository: notification_outbox 表 CRUD（enqueue 幂等 / list_pending / mark_*）
- EmailEnvelope: 演示 vs 生产模式投递地址 + 主题前缀 + 横幅差异收口
- EmailSender: aiosmtplib + QQ smtp.qq.com:465 + EmailMessage 自动 RFC 2047
- node_waiting_email 模板（jinja2 + table-based HTML，中文）

Slice 4D 才接入 APScheduler outbox_drain；Slice 4B 才加 Mattermost outbox。
"""

from __future__ import annotations

from .email_envelope import (
    DEMO_BANNER_TEMPLATE,
    ROLE_CN_MAP,
    EmailEnvelope,
    build_envelope,
)
from .email_sender import EmailSender, SendResult
from .outbox_repository import OutboxRepository

__all__ = [
    "DEMO_BANNER_TEMPLATE",
    "ROLE_CN_MAP",
    "EmailEnvelope",
    "EmailSender",
    "OutboxRepository",
    "SendResult",
    "build_envelope",
]
