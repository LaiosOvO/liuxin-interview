"""EmailSender 真 SMTP 集成测试 — 默认走 MailHog（本地 docker 起的）。

启动方式（任选其一）：
1. 本地装 MailHog 或 mailpit：
       docker run -d -p 1025:1025 -p 8025:8025 axllent/mailpit
   然后 pytest 自动连 localhost:1025（环境变量 MAILHOG_SMTP_HOST 可覆盖）
2. 跑测试时显式注入：
       MAILHOG_SMTP_HOST=mailhog.local MAILHOG_SMTP_PORT=1025 pytest -m integration

若 SMTP 端口不可达 → pytest.skip（CI 没启 MailHog 不会阻塞）。
真 QQ SMTP 测试**不放这里**（PITFALLS #14 频率限制），由 deploy 阶段手测一次。
"""

from __future__ import annotations

import json
import os
import socket
import uuid
from typing import Any

import httpx
import pytest

from offboarding_flow.config import Settings
from offboarding_flow.notifications.email_envelope import build_envelope
from offboarding_flow.notifications.email_sender import EmailSender


def _mailhog_smtp_host() -> str:
    return os.environ.get("MAILHOG_SMTP_HOST", "localhost")


def _mailhog_smtp_port() -> int:
    return int(os.environ.get("MAILHOG_SMTP_PORT", "1025"))


def _mailhog_api_host() -> str:
    return os.environ.get("MAILHOG_API_HOST", "localhost")


def _mailhog_api_port() -> int:
    """mailpit 默认 8025；MailHog 也是 8025。"""
    return int(os.environ.get("MAILHOG_API_PORT", "8025"))


def _smtp_reachable() -> bool:
    """探测 MailHog SMTP 端口是否可达（5s 超时）。"""
    try:
        with socket.create_connection((_mailhog_smtp_host(), _mailhog_smtp_port()), timeout=5):
            return True
    except (OSError, ConnectionRefusedError):
        return False


@pytest.fixture(scope="module")
def mailhog_settings() -> Settings:
    """指向 MailHog 的 Settings（不 use_tls，不需要密码）。"""
    return Settings(
        app_mode="demo",
        smtp_host=_mailhog_smtp_host(),
        smtp_port=_mailhog_smtp_port(),
        smtp_use_ssl=False,  # MailHog 是 plain SMTP，不要 SSL
        smtp_user="bot@test.local",
        smtp_password="ignored_by_mailhog",
        smtp_from_name="离职流程 Bot",
        demo_inbox="demo@qq.com",
    )


@pytest.fixture(autouse=True)
def _skip_if_no_mailhog() -> None:
    if not _smtp_reachable():
        pytest.skip(
            f"MailHog SMTP 不可达（{_mailhog_smtp_host()}:{_mailhog_smtp_port()}）— "
            "起 docker run -p 1025:1025 -p 8025:8025 axllent/mailpit 后重跑"
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_send_real_email_to_mailhog_demo_mode() -> None:
    """演示模式邮件实际发送到 MailHog — 验证 envelope + sender 端到端通畅。"""
    settings: Settings = Settings(
        app_mode="demo",
        smtp_host=_mailhog_smtp_host(),
        smtp_port=_mailhog_smtp_port(),
        smtp_use_ssl=False,
        smtp_user="bot@test.local",
        smtp_password="ignored",
        smtp_from_name="离职流程 Bot",
        demo_inbox="demo@qq.com",
    )

    unique_marker = uuid.uuid4().hex[:8]
    envelope = build_envelope(
        recipient_real="it.charlie@demo.local",
        base_subject=f"离职流程 — 张三 — 设备归还待处理 [{unique_marker}]",
        body_html=f"<p>测试邮件 marker={unique_marker}</p>",
        body_text=f"测试邮件 marker={unique_marker}",
        role="it_admin",
        username="it.charlie",
        settings=settings,
    )

    sender = EmailSender(settings)
    result = await sender.send(envelope)

    # 演示模式 → 投递到 demo@qq.com，subject 带 [设备管理员·it.charlie] 前缀
    assert result.delivery_to == "demo@qq.com"
    assert "[设备管理员·it.charlie]" in result.subject
    assert unique_marker in result.subject

    # 调 MailHog API 查最新邮件，验证主题正确编码（中文 / RFC 2047 round-trip）+ 收件人正确
    async with httpx.AsyncClient(timeout=10.0) as client:
        # mailpit 与 MailHog API 兼容：GET /api/v1/messages 列邮件
        for api_path in ("/api/v1/messages", "/api/v2/messages"):
            try:
                resp = await client.get(
                    f"http://{_mailhog_api_host()}:{_mailhog_api_port()}{api_path}"
                )
                if resp.status_code == 200:
                    break
            except httpx.RequestError:
                continue
        else:
            pytest.skip("MailHog API 不响应（可能没装 mailpit 也没 MailHog UI）")

        data: dict[str, Any] = resp.json()
        # mailpit: data['messages']; MailHog 旧版: data['items']
        messages = data.get("messages") or data.get("items") or []
        # 找带 marker 的那封
        found = None
        for msg in messages:
            # mailpit: msg['Subject']; MailHog: msg['Content']['Headers']['Subject']
            subj = (
                msg.get("Subject")
                or (msg.get("Content", {}).get("Headers", {}).get("Subject", [""])[0])
            )
            if unique_marker in str(subj):
                found = msg
                break

        assert found is not None, (
            f"MailHog 中没找到 marker={unique_marker} 的邮件；"
            f"messages count={len(messages)} sample={json.dumps(messages[:2], default=str)[:500]}"
        )
        # 主题正确解码（mailpit API 返回的 Subject 已 RFC 2047 解码）
        found_subject = (
            found.get("Subject")
            or (found.get("Content", {}).get("Headers", {}).get("Subject", [""])[0])
        )
        assert "[设备管理员·it.charlie]" in found_subject
        assert "张三" in found_subject
