"""EmailSender unit tests — mocked aiosmtplib（不真发 QQ SMTP）。

覆盖：
- 成功路径：smtp_client 被以正确参数调用
- 中文主题 RFC 2047 编码（PITFALLS #15）— 检 EmailMessage as_bytes 是 ASCII-safe
- 失败路径：SMTP 异常被包装成 SendError
- multipart/alternative：text + html 两个版本都在
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any

import pytest

from offboarding_flow.config import Settings
from offboarding_flow.notifications.email_envelope import EmailEnvelope, build_envelope
from offboarding_flow.notifications.email_sender import (
    EmailSender,
    SendError,
    _build_message,
)


def _make_settings() -> Settings:
    return Settings(
        app_mode="demo",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_use_ssl=True,
        smtp_user="bot@qq.com",
        smtp_password="dummy_authcode",
        smtp_from_name="离职流程 Bot",
        demo_inbox="demo@qq.com",
    )


def _make_envelope(settings: Settings) -> EmailEnvelope:
    # 用未在 DEMO_INBOX_MAP 中的 username，触发 fallback 到 settings.demo_inbox 走原测试路径
    return build_envelope(
        recipient_real="unknown.tester@demo.local",
        base_subject="离职流程 — 张三 — 设备归还待处理",
        body_html="<p>正文 HTML</p>",
        body_text="正文 text",
        role="it_admin",
        username="unknown.tester",
        settings=settings,
    )


# ---------------------------------------------------------------------------
# _build_message：RFC 2047 编码 + multipart/alternative
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_build_message_subject_is_ascii_safe_rfc_2047() -> None:
    """PITFALLS #15: 中文主题序列化后必须是 ASCII（RFC 2047 编码）。

    EmailMessage.as_bytes() 输出会 base64 / quoted-printable 编码非 ASCII header，
    本测试确保 stdlib 真的做了编码，不会出 raw 中文字节。
    """
    settings = _make_settings()
    envelope = _make_envelope(settings)
    msg = _build_message(envelope, settings)

    # Subject header 的 raw bytes — 必须能 ASCII decode
    raw = msg.as_bytes()
    # 找 Subject: 那一行
    subject_line = next(
        (line for line in raw.splitlines() if line.startswith(b"Subject:")),
        None,
    )
    assert subject_line is not None, "Subject header 缺失"
    # 整个 Subject 行（含 RFC 2047 编码）必须只含 ASCII
    try:
        subject_line.decode("ascii")
    except UnicodeDecodeError as e:
        pytest.fail(f"Subject 行含非 ASCII 字节，RFC 2047 编码失败：{e!r} raw={subject_line!r}")

    # 头部值应该包含 RFC 2047 marker（=?utf-8?…?=）
    # 因为 subject 含中文 + 含特殊字符 "·"
    assert (
        b"=?utf-8?" in subject_line or b"=?UTF-8?" in subject_line
    ), f"Subject 看起来没做 RFC 2047 编码：{subject_line!r}"


@pytest.mark.unit
def test_build_message_subject_round_trips_to_original_chinese() -> None:
    """编码 → parse 回来必须等于原中文（验证编码正确而不是乱码）。"""
    from email import message_from_bytes
    from email.policy import default

    settings = _make_settings()
    envelope = _make_envelope(settings)
    msg = _build_message(envelope, settings)
    raw = msg.as_bytes()

    parsed = message_from_bytes(raw, policy=default)
    assert parsed["Subject"] == envelope.subject


@pytest.mark.unit
def test_build_message_has_text_and_html_alternative() -> None:
    """正文必须是 multipart/alternative，两个版本都在 — fallback 老客户端用 text。"""
    settings = _make_settings()
    envelope = _make_envelope(settings)
    msg = _build_message(envelope, settings)

    # 主 content-type 应该是 multipart/alternative
    assert msg.get_content_type() == "multipart/alternative"
    parts = list(msg.iter_parts())
    types = [p.get_content_type() for p in parts]
    assert "text/plain" in types
    assert "text/html" in types


@pytest.mark.unit
def test_build_message_to_is_envelope_delivery_to_not_real() -> None:
    """演示模式：To header 是 delivery_to（DEMO_INBOX）而不是 recipient_real。"""
    settings = _make_settings()
    envelope = _make_envelope(settings)
    msg = _build_message(envelope, settings)
    assert msg["To"] == envelope.delivery_to
    assert envelope.delivery_to == "demo@qq.com"  # demo 模式覆写
    assert envelope.recipient_real == "unknown.tester@demo.local"  # 真值审计


@pytest.mark.unit
def test_build_message_rejects_malformed_smtp_user() -> None:
    """非法 SMTP_USER 直接抛 SendError，不让 Address 内部 traceback 泄露。"""
    settings = Settings(
        app_mode="demo",
        smtp_user="not_an_email",  # 没有 @
        smtp_password="x",
        smtp_from_name="Bot",
    )
    envelope = build_envelope(
        recipient_real="x@x.com",
        base_subject="s",
        body_html="<p/>",
        body_text="t",
        role="hr",
        username="u",
        settings=settings,
    )
    with pytest.raises(SendError, match="SMTP_USER"):
        _build_message(envelope, settings)


# ---------------------------------------------------------------------------
# EmailSender.send：mocked smtp_client
# ---------------------------------------------------------------------------


class _FakeSmtpClient:
    """记录 send 调用 + 可注入 raise — 测试用 mock。"""

    def __init__(
        self, *, response: tuple[dict, str] | None = None, raise_exc: Exception | None = None
    ) -> None:
        self.response = response or ({}, "250 OK")
        self.raise_exc = raise_exc
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        message: EmailMessage,
        *,
        hostname: str,
        port: int,
        username: str,
        password: str,
        use_tls: bool,
        timeout: float,
    ) -> tuple[dict, str]:
        self.calls.append(
            {
                "message": message,
                "hostname": hostname,
                "port": port,
                "username": username,
                "password": password,
                "use_tls": use_tls,
                "timeout": timeout,
            }
        )
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_invokes_smtp_with_qq_credentials() -> None:
    """send() 必须用 settings 的 host/port/user/use_tls 调 smtp。"""
    settings = _make_settings()
    fake = _FakeSmtpClient()
    sender = EmailSender(settings, smtp_client=fake)  # type: ignore[arg-type]
    envelope = _make_envelope(settings)

    result = await sender.send(envelope)

    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["hostname"] == "smtp.qq.com"
    assert call["port"] == 465
    assert call["use_tls"] is True
    assert call["username"] == "bot@qq.com"
    assert call["password"] == "dummy_authcode"
    assert isinstance(call["message"], EmailMessage)
    assert result.delivery_to == "demo@qq.com"
    assert "[演示模式" not in result.subject  # subject 不含横幅文本，只有前缀


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_failure_wraps_as_send_error() -> None:
    """底层 SMTP 异常被包装成 SendError，原异常作为 cause 保留。"""
    settings = _make_settings()
    underlying = RuntimeError("550 Ip frequency limited")
    fake = _FakeSmtpClient(raise_exc=underlying)
    sender = EmailSender(settings, smtp_client=fake)  # type: ignore[arg-type]
    envelope = _make_envelope(settings)

    with pytest.raises(SendError) as exc_info:
        await sender.send(envelope)

    assert "550" in str(exc_info.value)
    assert exc_info.value.__cause__ is underlying
