"""单元测试：workers.outbox_drain（NOTI-01 drain + NOTI-04 重试）。

策略：mock OutboxRepository + EmailSender / MattermostSender — 不依赖真 DB/SMTP/MM。
真集成测试 (PG LISTEN/NOTIFY 端到端) 留 integration 目录用 testcontainers。
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from offboarding_flow.workers.outbox_drain import (
    HEARTBEAT_SECONDS,
    MAX_RETRY_ATTEMPTS,
    OutboxDrainWorker,
    drain_once,
)


@pytest.fixture
def fake_settings():
    s = SimpleNamespace()
    s.app_mode = "demo"
    s.is_demo = True  # build_envelope 用
    s.demo_inbox = "1624456575@qq.com"
    s.smtp_host = "smtp.qq.com"
    s.smtp_port = 465
    s.smtp_user = "u@qq.com"
    s.smtp_password = "x"
    s.smtp_use_ssl = True
    s.smtp_from_name = "Bot"
    s.mattermost_url = "http://mm:8065"
    s.mattermost_bot_token = "tok"
    s.mattermost_http_timeout = 10.0
    s.langgraph_pg_conninfo = "postgres://fake"
    return s


def _make_row(channel: str, attempts: int = 0):
    """构造 fake NotificationOutbox 行（不依赖 ORM 实例）。"""
    row = MagicMock()
    row.id = uuid.uuid4()
    row.channel = channel
    row.recipient = "test@example.com" if channel == "email" else "channelid123"
    row.payload = {
        "subject": "测试主题",
        "html": "<p>html</p>",
        "text": "纯文本",
        "role": "manager",
        "username": "li.si",
        "message": "MM 测试",
        "attachments": [],
    }
    row.attempts = attempts
    return row


class TestDrainOnce:
    @pytest.mark.asyncio
    async def test_no_pending_returns_zero(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[])
            count = await drain_once(session, fake_settings)
            assert count == 0

    @pytest.mark.asyncio
    async def test_email_dispatch_success_marks_success(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        row = _make_row("email")
        mock_sender = AsyncMock()
        mock_sender.send = AsyncMock(return_value=MagicMock())
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[row])
            repo.mark_success = AsyncMock()
            repo.mark_failed = AsyncMock()
            count = await drain_once(session, fake_settings, email_sender=mock_sender)
            assert count == 1
            repo.mark_success.assert_called_once_with(row.id)
            repo.mark_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_email_dispatch_failure_marks_failed_with_backoff(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        row = _make_row("email", attempts=0)
        mock_sender = AsyncMock()
        mock_sender.send = AsyncMock(side_effect=RuntimeError("smtp boom"))
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[row])
            repo.mark_success = AsyncMock()
            repo.mark_failed = AsyncMock()
            count = await drain_once(session, fake_settings, email_sender=mock_sender)
            assert count == 1
            repo.mark_failed.assert_called_once()
            assert "smtp boom" in repo.mark_failed.call_args.args[1]
            # 第一次失败 retry_after_seconds=60
            assert repo.mark_failed.call_args.kwargs["retry_after_seconds"] == 60

    @pytest.mark.asyncio
    async def test_permanent_failure_after_max_attempts(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        session.execute = AsyncMock()
        row = _make_row("email", attempts=MAX_RETRY_ATTEMPTS - 1)  # 这次失败将达到 MAX
        mock_sender = AsyncMock()
        mock_sender.send = AsyncMock(side_effect=RuntimeError("fatal"))
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[row])
            repo.mark_success = AsyncMock()
            repo.mark_failed = AsyncMock()
            await drain_once(session, fake_settings, email_sender=mock_sender)
            # 应走 _mark_terminal_failure 路径（session.execute），不调 mark_failed
            repo.mark_failed.assert_not_called()
            session.execute.assert_called()

    @pytest.mark.asyncio
    async def test_mattermost_dispatch_success(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        row = _make_row("mattermost")
        mock_mm = AsyncMock()
        mock_mm.post = AsyncMock(return_value={"id": "post1"})
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[row])
            repo.mark_success = AsyncMock()
            repo.mark_failed = AsyncMock()
            count = await drain_once(session, fake_settings, mattermost_sender=mock_mm)
            assert count == 1
            mock_mm.post.assert_called_once()
            sent_msg = mock_mm.post.call_args.args[0]
            assert sent_msg.channel_id == row.recipient
            repo.mark_success.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_channel_marks_failed(self, fake_settings):
        session = MagicMock()
        session.commit = AsyncMock()
        row = _make_row("sms")  # 未实现
        with patch("offboarding_flow.workers.outbox_drain.OutboxRepository") as RepoCls:
            repo = RepoCls.return_value
            repo.list_pending = AsyncMock(return_value=[row])
            repo.mark_success = AsyncMock()
            repo.mark_failed = AsyncMock()
            await drain_once(session, fake_settings)
            repo.mark_success.assert_not_called()
            repo.mark_failed.assert_called_once()


class TestOutboxDrainWorkerLifecycle:
    @pytest.mark.asyncio
    async def test_stop_returns_quickly(self, fake_settings):
        worker = OutboxDrainWorker(fake_settings)
        # patch _safe_drain + _listen_loop 防真连 PG
        worker._safe_drain = AsyncMock()
        worker._listen_loop = AsyncMock(side_effect=lambda: asyncio.sleep(99))

        async def run_and_stop():
            task = asyncio.create_task(worker.run())
            await asyncio.sleep(0.05)
            await worker.stop()
            await asyncio.wait_for(task, timeout=2.0)

        await run_and_stop()
        # 启动时 + stop 时各 drain 一次（至少 2 次）
        assert worker._safe_drain.await_count >= 2

    def test_heartbeat_constant_safety_net_not_polling(self):
        # 心跳应该足够长以表达"非轮询"语义（不要是 10s 这种短时）
        assert HEARTBEAT_SECONDS >= 30, "心跳应是兜底而非主驱动 — 不要 < 30s 否则就变轮询"
