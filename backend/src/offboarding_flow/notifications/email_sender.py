"""EmailSender — aiosmtplib + QQ SMTP smtp.qq.com:465（PRD §7.4.3 + PITFALLS #14/#15）。

约定：
- 用 EmailMessage（不是 MIMEText）让 stdlib 自动 RFC 2047 编码中文主题（PITFALLS #15）
- QQ SMTP 必须 use_tls=True + port 465（不是 STARTTLS）
- 发件超时 30s 避免演示卡死（QQ 偶发慢）
- 失败抛 SendError（含 SMTP code + message），调用方决定重试 / 写 notifications.failed
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from offboarding_flow.config import Settings
    from offboarding_flow.notifications.email_envelope import EmailEnvelope

logger = logging.getLogger(__name__)

# 单封邮件 SMTP 超时（秒）— QQ 偶发慢，避免演示卡死
_SMTP_TIMEOUT_SECONDS = 30.0


class SendError(Exception):
    """SMTP 发送失败（含 timeout / auth / 频率限制 / 收件人拒绝）。"""

    def __init__(self, message: str, *, smtp_code: int | None = None) -> None:
        super().__init__(message)
        self.smtp_code = smtp_code


@dataclass(frozen=True)
class SendResult:
    """成功发送的元数据（写入 notifications 表 + log 用）。"""

    delivery_to: str
    subject: str
    smtp_response: str | None = None


class _SmtpClientProtocol(Protocol):
    """aiosmtplib.send 的最小接口 — 便于 unit test 注入 mock。"""

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
    ) -> tuple[dict, str]: ...


def _build_message(envelope: "EmailEnvelope", settings: "Settings") -> EmailMessage:
    """构造 EmailMessage — RFC 2047 编码 + multipart/alternative（text + html）。

    PITFALLS #15: 必须用 EmailMessage 不用 MIMEText，让 stdlib 自动编码中文 header。
    """
    msg = EmailMessage()
    msg["Subject"] = envelope.subject  # EmailMessage 自动 RFC 2047 编码非 ASCII
    # From: 显示名（中文）+ 邮箱地址 — Address 会自动正确编码
    smtp_user = settings.smtp_user
    if "@" not in smtp_user:
        # 兜底：避免 Address 解析失败导致整封邮件构造失败
        raise SendError(f"SMTP_USER 不是合法邮箱: {smtp_user!r}")
    local, _, domain = smtp_user.partition("@")
    msg["From"] = Address(
        display_name=settings.smtp_from_name,
        username=local,
        domain=domain,
    )
    msg["To"] = envelope.delivery_to
    msg.set_content(envelope.body_text)
    msg.add_alternative(envelope.body_html, subtype="html")
    return msg


class EmailSender:
    """SMTP 发件器 — 单例，无状态，方法级 async。"""

    def __init__(
        self,
        settings: "Settings",
        smtp_client: _SmtpClientProtocol | None = None,
    ) -> None:
        """注入 settings 与可选 smtp_client（默认 aiosmtplib.send，测试可 mock）。"""
        self.settings = settings
        self._smtp_client = smtp_client  # None → lazy import aiosmtplib

    async def send(self, envelope: "EmailEnvelope") -> SendResult:
        """发送一封邮件。

        Args:
            envelope: 已 build 完的 EmailEnvelope（delivery_to / subject / body 都最终化）

        Returns:
            SendResult: 含投递地址 + 主题 + SMTP 响应字符串（log 用）

        Raises:
            SendError: SMTP 失败（含超时 / auth / 频率限制 / 收件人拒绝）
        """
        msg = _build_message(envelope, self.settings)
        smtp_send = self._smtp_client
        if smtp_send is None:
            # 延迟 import：避免 aiosmtplib 缺包时 import notifications 整包炸
            import aiosmtplib  # type: ignore[import-not-found]

            smtp_send = aiosmtplib.send  # type: ignore[assignment]

        try:
            response = await smtp_send(  # type: ignore[misc]
                msg,
                hostname=self.settings.smtp_host,
                port=self.settings.smtp_port,
                username=self.settings.smtp_user,
                password=self.settings.smtp_password,
                use_tls=self.settings.smtp_use_ssl,
                timeout=_SMTP_TIMEOUT_SECONDS,
            )
            # aiosmtplib.send 返回 (errors_dict, response_str)
            response_str: str | None = None
            if isinstance(response, tuple) and len(response) >= 2:
                response_str = str(response[1])
            logger.info(
                "[email_sender] sent to=%s subject=%s demo=%s",
                envelope.delivery_to,
                envelope.subject,
                envelope.is_demo,
            )
            return SendResult(
                delivery_to=envelope.delivery_to,
                subject=envelope.subject,
                smtp_response=response_str,
            )
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "[email_sender] send FAILED to=%s subject=%s err=%s",
                envelope.delivery_to,
                envelope.subject,
                error_msg,
            )
            # 提取 SMTP code（如果是 aiosmtplib 的异常带 code 属性）
            smtp_code = getattr(exc, "code", None)
            raise SendError(error_msg, smtp_code=smtp_code) from exc
