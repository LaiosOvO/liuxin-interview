"""节点超时扫描 worker — Phase 6（NOTI-05 + TIMEOUT-01）。

PRD §17.1 逾期模拟：
- 默认 SLA = NODE_TIMEOUT_HOURS（24h）
- 演示快速触发：DEMO_TIMEOUT_OVERRIDE_HOURS（如 0.05 = 3 分钟，仅 demo 模式生效）
- APScheduler-like 后台循环：每 60s 扫一次 `node_states WHERE status='waiting_human' AND entered_at < now() - SLA`
- 命中节点：标记 `is_overdue=True` + enqueue 重发提醒邮件（assignee + cc HR）

设计要点（继承 outbox_drain.py 模式）：
1. 用 asyncio.sleep(interval) 心跳，不依赖 APScheduler 包（依赖少 + 与 outbox_drain 一致）
2. 幂等：一个节点超时只入队一次重发提醒（通过 action_logs `timeout_remind_sent` 标识）
3. 失败容错：单次扫描出错不死循环，下一周期继续
4. 优雅停止：FastAPI lifespan shutdown → set stop_event + await join

REQ: NOTI-05 (定时重发提醒) + TIMEOUT-01 (SLA 标记 is_overdue)
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select, update

from offboarding_flow.notifications import OutboxRepository
from offboarding_flow.state_store.enums import ActionStatus, NodeStatus
from offboarding_flow.state_store.models import ActionLog, FlowInstance, NodeState
from offboarding_flow.state_store.repositories import UserRepository
from offboarding_flow.state_store.session import new_session

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from offboarding_flow.config import Settings

logger = logging.getLogger(__name__)

# action_logs 标识：本节点已发过超时提醒（幂等防重发）
TIMEOUT_REMIND_ACTION = "timeout_remind_sent"

# 单次扫描最多处理多少超时节点（防 N+1 大批量）
SCAN_BATCH_SIZE = 50


def compute_sla_hours(settings: "Settings") -> float:
    """计算当前生效的 SLA 小时数。

    优先级（PRD §17.1）：
        demo 模式 + DEMO_TIMEOUT_OVERRIDE_HOURS 已设 → 用 override
        否则                                       → 用 NODE_TIMEOUT_HOURS（默认 24h）

    Returns:
        SLA 小时数（float，支持 0.05 ≈ 3 分钟的演示场景）
    """
    if settings.app_mode == "demo" and settings.demo_timeout_override_hours is not None:
        return float(settings.demo_timeout_override_hours)
    return float(settings.node_timeout_hours)


def compute_threshold(settings: "Settings", now: datetime | None = None) -> datetime:
    """计算超时阈值时间戳（小于该时间戳的 entered_at 视为超时）。

    Args:
        settings: 全局配置
        now: 测试用时间注入；默认 datetime.now(UTC)

    Returns:
        阈值 datetime（UTC）。entered_at < threshold 即超时。
    """
    sla_hours = compute_sla_hours(settings)
    current = now if now is not None else datetime.now(UTC)
    return current - timedelta(hours=sla_hours)


async def find_overdue_nodes(
    session: "AsyncSession",
    settings: "Settings",
    *,
    now: datetime | None = None,
    limit: int = SCAN_BATCH_SIZE,
) -> list[NodeState]:
    """查找超过 SLA 仍 waiting_human 的节点。

    SQL 语义：
        SELECT * FROM app.node_states
        WHERE status = 'waiting_human'
          AND entered_at IS NOT NULL
          AND entered_at < :threshold
        ORDER BY entered_at ASC
        LIMIT :limit

    注：is_overdue 已标记的节点仍会被取出（用于重发提醒，由 enqueue 幂等 + action_log 二次防重）。
    """
    threshold = compute_threshold(settings, now=now)
    stmt = (
        select(NodeState)
        .where(
            NodeState.status == NodeStatus.WAITING_HUMAN.value,
            NodeState.entered_at.is_not(None),
            NodeState.entered_at < threshold,
        )
        .order_by(NodeState.entered_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _has_been_reminded(
    session: "AsyncSession",
    node_state_id: uuid.UUID,
) -> bool:
    """检查该节点是否已发过超时提醒（幂等防重发）。

    用 action_logs.action='timeout_remind_sent' 作幂等标识。
    """
    stmt = (
        select(ActionLog.id)
        .where(
            ActionLog.node_state_id == node_state_id,
            ActionLog.action == TIMEOUT_REMIND_ACTION,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def _mark_overdue(session: "AsyncSession", node_state_id: uuid.UUID) -> None:
    """标记 node_states.is_overdue=True（幂等，已 True 也无副作用）。"""
    stmt = (
        update(NodeState)
        .where(NodeState.id == node_state_id, NodeState.is_overdue.is_(False))
        .values(is_overdue=True)
    )
    await session.execute(stmt)


def _build_timeout_reminder_payload(node: NodeState, flow: FlowInstance | None) -> dict:
    """构造超时提醒邮件 payload（schema 对齐 outbox_drain._envelope_from_payload）。

    outbox_drain 读 payload['subject'] / ['html'] / ['text'] / ['role'] / ['username']。
    """
    employee_id = flow.employee_id if flow is not None else "unknown"
    assignee = node.assignee or "unknown"
    subject = f"[超时提醒] {node.node_title} — {employee_id} 离职流程"
    body_text = (
        f"亲爱的 {assignee}：\n\n"
        f"流程 {employee_id} 的【{node.node_title}】节点已超过 SLA 仍未处理，请尽快推进。\n"
        f"节点 ID: {node.id}\n"
        f"进入时间: {node.entered_at.isoformat() if node.entered_at else 'N/A'}\n\n"
        "如已处理但状态未更新，请联系 HR 协调。\n"
    )
    body_html = (
        f"<p>亲爱的 <strong>{assignee}</strong>：</p>"
        f"<p>流程 <code>{employee_id}</code> 的【<strong>{node.node_title}</strong>】"
        f"节点已超过 SLA 仍未处理，请尽快推进。</p>"
        f"<ul>"
        f"<li>节点 ID: <code>{node.id}</code></li>"
        f"<li>进入时间: {node.entered_at.isoformat() if node.entered_at else 'N/A'}</li>"
        f"</ul>"
        "<p>如已处理但状态未更新，请联系 HR 协调。</p>"
    )
    return {
        "subject": subject,
        "html": body_html,
        "text": body_text,
        "role": "reminder",  # 演示模式角色前缀走 "提醒" 语义
        "username": assignee,
        # 携带元数据辅助 debug / 审计
        "event": "timeout_reminder",
        "node_state_id": str(node.id),
        "flow_id": str(node.flow_id),
    }


async def enqueue_timeout_reminders(
    session: "AsyncSession",
    nodes: list[NodeState],
    settings: "Settings",
) -> int:
    """对超时节点入队提醒邮件 + 写 action_log 幂等标识。

    流程：
        for each node:
            1. is_overdue 标 True（幂等）
            2. 已发过提醒 → skip
            3. 查 flow / 查 assignee email
            4. enqueue email outbox（recipient 默认 assignee；演示模式 envelope 层会覆写到 DEMO_INBOX）
            5. 写 action_log action='timeout_remind_sent' 幂等
            6. signal_outbox_pending() 唤醒 drain（在 caller 层一次性调）

    Returns:
        实际新入队的提醒数（不含 skip）。
    """
    user_repo = UserRepository(session)
    outbox_repo = OutboxRepository(session)
    reminded_count = 0

    for node in nodes:
        # 1. 标 is_overdue
        await _mark_overdue(session, node.id)

        # 2. 已发过提醒 → skip
        if await _has_been_reminded(session, node.id):
            logger.debug("[timeout_scan] node=%s already reminded, skip", node.id)
            continue

        # 3. 查 flow + assignee
        flow = await session.get(FlowInstance, node.flow_id)
        assignee_email = node.assignee or "unknown@unknown"
        if node.assignee:
            user = await user_repo.get_by_username(node.assignee)
            if user is not None and user.email:
                assignee_email = user.email

        # 4. enqueue email outbox（recipient 真值；envelope 层 demo 模式覆写）
        # 注意：channel='email_timeout' 而非 'email' — 避开 UNIQUE(flow_id, node_state_id, 'email')
        # 与首次通知冲突。drain 仍按 channel.startswith('email') 走 email 分支即可，
        # 但当前 drain 只识别 'email' / 'mattermost'；TIMEOUT-01 v1 用 (flow_id=None) 入队避冲突。
        # 简化方案：用 (flow_id, None, channel='email') — node_state_id 设 None 让 UNIQUE 不冲突。
        outbox_row = await outbox_repo.enqueue(
            flow_id=node.flow_id,
            node_state_id=None,  # 超时提醒不挂业务节点 — 避开 UNIQUE 与首次通知冲突
            channel="email",
            recipient=assignee_email,
            payload=_build_timeout_reminder_payload(node, flow),
        )
        if outbox_row is None:
            # 极少数情况：(flow_id, None, 'email') 已存在（可能上次扫描已入但 action_log 没写）
            # 仍写 action_log 防下次再扫
            logger.warning(
                "[timeout_scan] outbox enqueue skipped (UNIQUE conflict) flow=%s node=%s",
                node.flow_id,
                node.id,
            )

        # 5. 写 action_log 幂等标识
        action = ActionLog(
            flow_id=node.flow_id,
            node_state_id=node.id,
            actor="system:timeout_scan",
            action=TIMEOUT_REMIND_ACTION,
            result_text=f"超时提醒已入队 — {node.node_title}",
            status=ActionStatus.SUCCESS.value,
            payload={
                "assignee": node.assignee,
                "recipient": assignee_email,
                "outbox_id": str(outbox_row.id) if outbox_row else None,
            },
        )
        session.add(action)
        reminded_count += 1

        logger.info(
            "[timeout_scan] reminder enqueued node=%s assignee=%s recipient=%s outbox=%s",
            node.id,
            node.assignee,
            assignee_email,
            outbox_row.id if outbox_row else "skipped",
        )

    return reminded_count


async def scan_once(
    session: "AsyncSession",
    settings: "Settings",
    *,
    now: datetime | None = None,
) -> tuple[int, int]:
    """单次扫描 — 找超时节点 + 入队提醒。

    Returns:
        (found_count, reminded_count) — 找到的超时节点数 / 新入队的提醒数
    """
    nodes = await find_overdue_nodes(session, settings, now=now)
    if not nodes:
        logger.debug("[timeout_scan] no overdue nodes")
        return 0, 0

    logger.info(
        "[timeout_scan] found %d overdue nodes (SLA=%.2fh, mode=%s)",
        len(nodes),
        compute_sla_hours(settings),
        settings.app_mode,
    )
    reminded = await enqueue_timeout_reminders(session, nodes, settings)
    return len(nodes), reminded


# ---------------------------------------------------------------------------
# 后台 worker — 与 OutboxDrainWorker 同 pattern
# ---------------------------------------------------------------------------
class TimeoutScanWorker:
    """长生命周期 worker — 定时扫描超时节点 + 触发提醒重发。

    生命周期（main.py lifespan 管理）：
        worker = TimeoutScanWorker(settings)
        task = asyncio.create_task(worker.run())
        # ... 服务运行 ...
        await worker.stop()
        await task

    与 OutboxDrainWorker 协作：
        timeout_scan enqueue outbox 后调 signal_outbox_pending() → drain 立即拉取发送
    """

    def __init__(self, settings: "Settings") -> None:
        self._settings = settings
        self._stop_event = asyncio.Event()
        self._interval = float(settings.timeout_scan_interval_seconds)

    async def run(self) -> None:
        """主循环：心跳 interval 触发 scan_once。"""
        sla = compute_sla_hours(self._settings)
        logger.info(
            "[timeout_scan] worker starting — interval=%.0fs SLA=%.2fh mode=%s "
            "(NOTI-05 + TIMEOUT-01)",
            self._interval,
            sla,
            self._settings.app_mode,
        )
        cycle = 0
        # 启动后稍等再扫，避免与 init 抢资源
        await self._sleep_or_stop(self._interval)
        try:
            while not self._stop_event.is_set():
                cycle += 1
                await self._safe_scan(cycle)
                await self._sleep_or_stop(self._interval)
        finally:
            logger.info("[timeout_scan] worker stopped (ran %d cycles)", cycle)

    async def stop(self) -> None:
        """请求停止 worker（FastAPI lifespan shutdown 调）。"""
        self._stop_event.set()

    async def _sleep_or_stop(self, seconds: float) -> None:
        """等 N 秒或被 stop 提前唤醒。"""
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

    async def _safe_scan(self, cycle: int) -> None:
        """单次扫描 — 捕获顶层异常防 worker 死。"""
        try:
            async with new_session() as session:
                found, reminded = await scan_once(session, self._settings)
                await session.commit()
                if reminded > 0:
                    logger.info(
                        "[timeout_scan] cycle %d — found=%d reminded=%d",
                        cycle,
                        found,
                        reminded,
                    )
                    # 唤醒 outbox drain 立即处理新入队的提醒邮件
                    from offboarding_flow.workers.outbox_drain import signal_outbox_pending

                    signal_outbox_pending()
        except Exception as exc:
            logger.exception("[timeout_scan] cycle %d failed (will retry): %s", cycle, exc)
