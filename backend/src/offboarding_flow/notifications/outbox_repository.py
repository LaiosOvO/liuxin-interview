"""notification_outbox 表 Repository — outbox 模式入队 / 取队 / 状态变更。

约定（继承 state_store/repositories.py 风格）：
- 不主动 commit — 调用方控制事务边界（保证业务事务内 enqueue 与节点状态变更原子）
- enqueue 用 PG INSERT ... ON CONFLICT DO NOTHING 实现幂等
  （NotificationOutbox 表已有 UNIQUE(flow_id, node_state_id, channel) 约束 — Phase 1 建表时已加）
- list_pending 用 SELECT ... FOR UPDATE SKIP LOCKED 防多 worker 竞争（Slice 4D drain job 用得到）
- 失败 attempts++、next_attempt_at 指数退避（Slice 4D 重试逻辑用得到，这里只暴露原子接口）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.state_store.enums import NotificationStatus
from offboarding_flow.state_store.models import NotificationOutbox


class OutboxRepository:
    """notification_outbox 表 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        flow_id: uuid.UUID,
        node_state_id: uuid.UUID | None,
        channel: str,
        recipient: str,
        payload: dict,
    ) -> NotificationOutbox | None:
        """幂等入队一条 outbox 记录。

        命中 UNIQUE(flow_id, node_state_id, channel) 时返回 None
        （表示该节点 + 通道已经在 outbox 中 — LangGraph interrupt 重跑场景）。

        Args:
            flow_id: 流程 id
            node_state_id: 节点 id（可空，flow-level 通知如 archived 通知）
            channel: 'email' / 'mattermost'
            recipient: 真实收件地址（审计真相，演示模式由 envelope 层覆写为 DEMO_INBOX）
            payload: JSONB，由消费者 (drain job) 渲染模板时取数据用

        Returns:
            新插入行的 ORM 实例；冲突时返回 None。
        """
        stmt = (
            pg_insert(NotificationOutbox)
            .values(
                flow_id=flow_id,
                node_state_id=node_state_id,
                channel=channel,
                recipient=recipient,
                payload=payload,
                status=NotificationStatus.PENDING.value,
            )
            .on_conflict_do_nothing(
                index_elements=["flow_id", "node_state_id", "channel"],
            )
            .returning(NotificationOutbox)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pending(
        self,
        limit: int = 20,
        now: datetime | None = None,
    ) -> list[NotificationOutbox]:
        """取一批 pending（且 next_attempt_at 已到）的 outbox 行。

        用 SELECT ... FOR UPDATE SKIP LOCKED 防多 worker 重复消费（Slice 4D drain 用得到）。
        """
        if now is None:
            now = datetime.now(UTC)
        stmt = (
            select(NotificationOutbox)
            .where(
                NotificationOutbox.status == NotificationStatus.PENDING.value,
                NotificationOutbox.next_attempt_at <= now,
            )
            .order_by(NotificationOutbox.next_attempt_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, outbox_id: uuid.UUID) -> NotificationOutbox | None:
        return await self.session.get(NotificationOutbox, outbox_id)

    async def mark_success(self, outbox_id: uuid.UUID) -> None:
        """标记为已发送（status=sent，由 Slice 4D drain 成功后调）。"""
        stmt = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id == outbox_id)
            .values(
                status=NotificationStatus.SENT.value,
                last_error=None,
            )
        )
        await self.session.execute(stmt)

    async def mark_failed(
        self,
        outbox_id: uuid.UUID,
        error_message: str,
        *,
        retry_after_seconds: int = 60,
    ) -> None:
        """标记一次失败 — attempts++，next_attempt_at 推迟（指数退避策略）。

        Slice 4D 会根据 attempts 阈值（如 >=3）切换 status 到 'failed'，
        当前仅暴露原子接口，不在这里做策略判断（避免与 drain 调度耦合）。
        """
        next_at = datetime.now(UTC) + timedelta(seconds=retry_after_seconds)
        stmt = (
            update(NotificationOutbox)
            .where(NotificationOutbox.id == outbox_id)
            .values(
                attempts=NotificationOutbox.attempts + 1,
                next_attempt_at=next_at,
                last_error=error_message,
            )
        )
        await self.session.execute(stmt)
