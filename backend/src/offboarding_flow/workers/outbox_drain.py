"""Outbox drain worker — 机制层 in-process 事件驱动 + 心跳兜底。

用户明确："事件驱动是机制上事件驱动不是数据库的事件驱动"。

实现策略：
1. **机制层 in-process 事件**：模块级单例 `asyncio.Event` `_OUTBOX_PENDING_EVENT`
   - 业务侧 enqueue outbox 行 + commit 事务后，调 `signal_outbox_pending()` 立即唤醒 worker
   - 不走 DB LISTEN/NOTIFY、不引入外部消息中间件、不轮询
   - 同进程零开销
2. **心跳兜底**：60s — 处理 signal_outbox_pending 漏调用 / worker 重启窗口
3. **重试**：drain 失败 → mark_failed（指数退避 60s/120s/240s 由 OutboxRepository 控制）
4. **优雅停止**：FastAPI lifespan shutdown → cancel + await 5s drain 剩余 pending

REQ: NOTI-01 (drain 部分) + NOTI-04 (重试 / notifications 表写入)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import TYPE_CHECKING

from offboarding_flow.notifications import (
    EmailSender,
    MattermostMessage,
    MattermostSender,
    OutboxRepository,
)
from offboarding_flow.state_store.enums import NotificationStatus
from offboarding_flow.state_store.session import new_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from offboarding_flow.config import Settings
    from offboarding_flow.state_store.models import NotificationOutbox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块级 in-process 事件（机制层事件驱动核心）
# ---------------------------------------------------------------------------
# 业务侧 enqueue outbox 行后调 signal_outbox_pending() 唤醒 worker。
# 单进程内全局共享，跨进程场景需切别的机制（v1 单 worker 单进程，足够）。
_OUTBOX_PENDING_EVENT: asyncio.Event | None = None


def _ensure_event() -> asyncio.Event:
    """惰性创建 event（需 running loop 上下文）。"""
    global _OUTBOX_PENDING_EVENT
    if _OUTBOX_PENDING_EVENT is None:
        _OUTBOX_PENDING_EVENT = asyncio.Event()
    return _OUTBOX_PENDING_EVENT


def signal_outbox_pending() -> None:
    """业务侧 enqueue commit 后调用，立即唤醒 outbox worker。

    使用约定（PRD §7 + Slice 4D）：
        async with new_session() as session:
            await notification_service.enqueue_node_email(...)
            await session.commit()
        # commit 之后再调（保证 worker 读得到）
        signal_outbox_pending()

    若调用时 event 还未创建（应用未启动 worker），no-op；不抛错。
    """
    if _OUTBOX_PENDING_EVENT is not None:
        logger.debug("[outbox_drain] signal_outbox_pending() — waking worker")
        _OUTBOX_PENDING_EVENT.set()
    else:
        logger.debug("[outbox_drain] signal_outbox_pending() — no worker started, skip")


def _reset_for_tests() -> None:
    """测试用 — 清除 module 级 event，下次 _ensure_event() 重建。"""
    global _OUTBOX_PENDING_EVENT
    _OUTBOX_PENDING_EVENT = None


# 心跳兜底秒数（非主驱动 — 处理 signal 漏调用 / worker 重启窗口）
HEARTBEAT_SECONDS = 60.0
# 单次 drain 最多拉多少行
DRAIN_BATCH_SIZE = 20
# 失败 attempts 阈值 → 切 status='failed'
MAX_RETRY_ATTEMPTS = 3
# 失败退避秒数（指数）
_RETRY_BACKOFF = (60, 120, 240)


async def drain_once(
    session: "AsyncSession",
    settings: "Settings",
    *,
    email_sender: EmailSender | None = None,
    mattermost_sender: MattermostSender | None = None,
) -> int:
    """单次 drain — 拉一批 pending 行 → 分通道发送 → mark success/failed。

    返回处理行数（不论成功失败）。0 = 队列空。
    每行处理完即 commit（隔离成功/失败状态）。
    """
    repo = OutboxRepository(session)
    logger.debug(
        "[outbox_drain] drain_once entered — querying pending (limit=%d)", DRAIN_BATCH_SIZE
    )
    rows = await repo.list_pending(limit=DRAIN_BATCH_SIZE)
    if not rows:
        logger.debug("[outbox_drain] no pending rows")
        return 0

    logger.info("[outbox_drain] picked %d pending rows", len(rows))
    processed = 0
    for row in rows:
        logger.debug(
            "[outbox_drain] dispatch begin id=%s channel=%s recipient=%s attempts=%d payload_keys=%s",
            row.id,
            row.channel,
            row.recipient,
            row.attempts or 0,
            list((row.payload or {}).keys()),
        )
        try:
            await _dispatch(row, settings, email_sender, mattermost_sender)
            await repo.mark_success(row.id)
            logger.info(
                "[outbox_drain] sent ok id=%s channel=%s recipient=%s",
                row.id,
                row.channel,
                row.recipient,
            )
        except Exception as exc:
            attempts = (row.attempts or 0) + 1
            err = f"{type(exc).__name__}: {exc}"
            if attempts >= MAX_RETRY_ATTEMPTS:
                await _mark_terminal_failure(session, row.id, err)
                logger.error(
                    "[outbox_drain] PERMANENT FAIL id=%s attempts=%d err=%s",
                    row.id,
                    attempts,
                    err,
                )
            else:
                backoff = _RETRY_BACKOFF[min(attempts - 1, len(_RETRY_BACKOFF) - 1)]
                await repo.mark_failed(row.id, err, retry_after_seconds=backoff)
                logger.warning(
                    "[outbox_drain] retry id=%s attempt=%d backoff=%ds err=%s",
                    row.id,
                    attempts,
                    backoff,
                    err,
                )
        await session.commit()
        processed += 1

    return processed


async def _dispatch(
    row: "NotificationOutbox",
    settings: "Settings",
    email_sender: EmailSender | None,
    mattermost_sender: MattermostSender | None,
) -> None:
    """按 channel 分发到具体 sender。失败 raise，由 caller 接异常做退避。"""
    payload = row.payload or {}
    if row.channel == "email":
        email = email_sender or EmailSender(settings)
        envelope = _envelope_from_payload(payload, recipient=row.recipient, settings=settings)
        await email.send(envelope)
    elif row.channel == "mattermost":
        if mattermost_sender is None:
            # 失败回退：未注入 sender 时构造 short-lived（仅测试 / 启动期）
            async with MattermostSender(settings) as s:
                await s.post(_mattermost_message_from_payload(payload, row.recipient))
            return
        await mattermost_sender.post(_mattermost_message_from_payload(payload, row.recipient))
    else:
        raise ValueError(f"unknown channel: {row.channel}")


def _envelope_from_payload(payload: dict, *, recipient: str, settings: "Settings"):
    """从 outbox.payload 构造 EmailEnvelope（Slice 4A enqueue 时约定的 schema）。"""
    from offboarding_flow.notifications import build_envelope

    return build_envelope(
        recipient_real=recipient,
        base_subject=payload.get("subject", "（无主题）"),
        body_html=payload.get("html", ""),
        body_text=payload.get("text") or "",
        role=payload.get("role") or "employee",
        username=payload.get("username") or "unknown",
        settings=settings,
    )


def _mattermost_message_from_payload(payload: dict, recipient: str) -> MattermostMessage:
    """从 outbox.payload 构造 MattermostMessage。recipient 是 channel_id（非 email）。"""
    return MattermostMessage(
        channel_id=recipient,
        message=payload.get("message") or payload.get("text") or "",
        attachments=payload.get("attachments") or [],
    )


async def _mark_terminal_failure(
    session: "AsyncSession",
    outbox_id: uuid.UUID,
    error_message: str,
) -> None:
    """attempts 用尽 → 切 status='failed'（list_pending 不再取）。"""
    from sqlalchemy import update

    from offboarding_flow.state_store.models import NotificationOutbox

    await session.execute(
        update(NotificationOutbox)
        .where(NotificationOutbox.id == outbox_id)
        .values(
            status=NotificationStatus.FAILED.value,
            last_error=error_message,
            attempts=NotificationOutbox.attempts + 1,
        )
    )


# ---------------------------------------------------------------------------
# 事件驱动 worker
# ---------------------------------------------------------------------------
class OutboxDrainWorker:
    """长生命周期 worker — 等 in-process asyncio.Event + 60s 心跳兜底。

    架构（用户明确：机制层事件驱动，非 DB 触发器）：
        业务侧 enqueue + commit 后调 signal_outbox_pending()
            ↓
        worker._wait_for_signal_or_heartbeat() 立即返回
            ↓
        drain_once() 拉队列 → 发邮件 / Mattermost → mark success/failed
            ↓
        清 event，进入下一轮等待

    生命周期（main.py lifespan 管理）：
        worker = OutboxDrainWorker(settings)
        task = asyncio.create_task(worker.run())
        # ... 服务运行 ...
        await worker.stop()
        await task
    """

    def __init__(
        self,
        settings: "Settings",
        *,
        email_sender: EmailSender | None = None,
        mattermost_sender: MattermostSender | None = None,
    ) -> None:
        self._settings = settings
        self._email_sender = email_sender
        self._mattermost_sender = mattermost_sender
        self._stop_event = asyncio.Event()
        # 触发 worker 的 in-process 事件；外部通过 signal_outbox_pending() 唤醒
        self._signal_event = _ensure_event()

    async def run(self) -> None:
        """主循环：drain 启动 → 等 signal | heartbeat | stop → drain → 循环。"""
        logger.info(
            "[outbox_drain] worker starting "
            "(in-process event-driven via asyncio.Event + %.0fs heartbeat fallback)",
            HEARTBEAT_SECONDS,
        )
        cycle = 0
        # 启动后立即 drain 一次（处理上次未消费的 pending）
        await self._safe_drain()
        try:
            while not self._stop_event.is_set():
                cycle += 1
                logger.debug("[outbox_drain] cycle %d — awaiting signal or heartbeat", cycle)
                await self._wait_for_signal_or_heartbeat()
                if self._stop_event.is_set():
                    logger.debug("[outbox_drain] cycle %d — stop requested, exiting loop", cycle)
                    break
                # 清 event 后立即 drain（之后 signal 会再次 set，不丢消息）
                woken_by_signal = self._signal_event.is_set()
                self._signal_event.clear()
                logger.debug(
                    "[outbox_drain] cycle %d — woken by %s, draining",
                    cycle,
                    "signal" if woken_by_signal else "heartbeat",
                )
                await self._safe_drain()
        finally:
            # 优雅 drain 剩余
            logger.debug("[outbox_drain] final drain before stop")
            await self._safe_drain()
            logger.info("[outbox_drain] worker stopped (ran %d cycles)", cycle)

    async def stop(self) -> None:
        """请求停止 worker（FastAPI lifespan shutdown 调）。"""
        self._stop_event.set()
        # 唤醒主循环，让它走到 stop 判定
        self._signal_event.set()

    async def _wait_for_signal_or_heartbeat(self) -> None:
        """等待 signal_event 被外部 set，或心跳超时，或 stop_event。

        三种唤醒源任一发生即返回。最早的获胜。
        """
        signal_task = asyncio.create_task(self._signal_event.wait())
        stop_task = asyncio.create_task(self._stop_event.wait())
        try:
            done, pending = await asyncio.wait(
                {signal_task, stop_task},
                timeout=HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, BaseException):
                    await task
        except asyncio.CancelledError:
            signal_task.cancel()
            stop_task.cancel()
            raise

    async def _safe_drain(self) -> None:
        """drain 一次，捕获顶层异常防 worker 死。"""
        try:
            async with new_session() as session:
                count = await drain_once(
                    session,
                    self._settings,
                    email_sender=self._email_sender,
                    mattermost_sender=self._mattermost_sender,
                )
                if count > 0:
                    logger.info("[outbox_drain] processed %d rows in this batch", count)
        except Exception as exc:
            logger.exception("[outbox_drain] drain cycle failed (will retry on next wake): %s", exc)


# ---------------------------------------------------------------------------
# 测试辅助 — 手动触发一次 drain（不依赖 worker 实例）
# ---------------------------------------------------------------------------
async def drain_now(
    settings: "Settings",
    *,
    email_sender: EmailSender | None = None,
    mattermost_sender: MattermostSender | None = None,
) -> int:
    """便捷函数：开一个新 session 跑一次 drain（测试 / 命令行用）。"""
    async with new_session() as session:
        return await drain_once(
            session,
            settings,
            email_sender=email_sender,
            mattermost_sender=mattermost_sender,
        )
