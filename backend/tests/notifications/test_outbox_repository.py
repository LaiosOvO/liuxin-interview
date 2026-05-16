"""OutboxRepository unit-ish tests — 需真 PG（DB 不可达自动 skip）。

覆盖：
- enqueue 幂等：第二次同 (flow_id, node_state_id, channel) 返回 None
- list_pending 只取 status=pending 且 next_attempt_at <= now
- mark_success / mark_failed 状态机
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.notifications.outbox_repository import OutboxRepository
from offboarding_flow.state_store.enums import NodeStatus, NotificationStatus
from offboarding_flow.state_store.models import FlowInstance, NodeState


@pytest_asyncio.fixture
async def flow_and_node(db_session: AsyncSession):
    """造一个 flow + 一个 waiting_human 节点 — outbox 测试用 FK target。"""
    flow = FlowInstance(id=uuid.uuid4(), employee_id="zhang.san", status="in_progress")
    node = NodeState(
        id=uuid.uuid4(),
        flow_id=flow.id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
        assignee="li.si",
    )
    db_session.add_all([flow, node])
    await db_session.commit()
    try:
        yield {"flow": flow, "node": node}
    finally:
        await db_session.delete(node)
        await db_session.delete(flow)
        await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enqueue_returns_row_on_first_call(
    db_session: AsyncSession, flow_and_node: dict
) -> None:
    repo = OutboxRepository(db_session)
    row = await repo.enqueue(
        flow_id=flow_and_node["flow"].id,
        node_state_id=flow_and_node["node"].id,
        channel="email",
        recipient="li.si@demo.local",
        payload={"node_name": "manager_review"},
    )
    assert row is not None
    assert row.status == NotificationStatus.PENDING.value
    assert row.recipient == "li.si@demo.local"
    assert row.payload["node_name"] == "manager_review"
    await db_session.commit()
    await db_session.delete(row)
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_enqueue_is_idempotent_on_unique_conflict(
    db_session: AsyncSession, flow_and_node: dict
) -> None:
    """REQ-NOTI-04: 第二次同 (flow_id, node_state_id, channel) 入队返回 None（不抛）。

    覆盖 LangGraph interrupt 重跑场景 — 节点函数被多次执行，outbox 不能重复入队。
    """
    repo = OutboxRepository(db_session)
    first = await repo.enqueue(
        flow_id=flow_and_node["flow"].id,
        node_state_id=flow_and_node["node"].id,
        channel="email",
        recipient="li.si@demo.local",
        payload={"v": 1},
    )
    assert first is not None
    await db_session.commit()

    # 同 key 再 enqueue 一次（演示 LangGraph 重跑）
    second = await repo.enqueue(
        flow_id=flow_and_node["flow"].id,
        node_state_id=flow_and_node["node"].id,
        channel="email",
        recipient="li.si@demo.local",
        payload={"v": 2},  # payload 不同也不会更新
    )
    assert second is None  # ON CONFLICT DO NOTHING

    await db_session.delete(first)
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_pending_skips_future_next_attempt(
    db_session: AsyncSession, flow_and_node: dict
) -> None:
    """list_pending 只返回 next_attempt_at <= now 的行（重试退避正确性）。"""
    repo = OutboxRepository(db_session)
    row = await repo.enqueue(
        flow_id=flow_and_node["flow"].id,
        node_state_id=flow_and_node["node"].id,
        channel="email",
        recipient="x@x.com",
        payload={},
    )
    assert row is not None
    await db_session.commit()

    # 标失败 → next_attempt_at 推 60s
    await repo.mark_failed(row.id, "fake error", retry_after_seconds=60)
    await db_session.commit()

    # 当前时间查 → 不应包含这行
    pending_now = await repo.list_pending(now=datetime.now(UTC))
    assert all(r.id != row.id for r in pending_now)

    # 把时间推到 2 分钟后 → 应该包含
    future = datetime.now(UTC) + timedelta(seconds=120)
    pending_future = await repo.list_pending(now=future)
    assert any(r.id == row.id for r in pending_future)

    await db_session.delete(row)
    await db_session.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_mark_success_clears_error(db_session: AsyncSession, flow_and_node: dict) -> None:
    repo = OutboxRepository(db_session)
    row = await repo.enqueue(
        flow_id=flow_and_node["flow"].id,
        node_state_id=flow_and_node["node"].id,
        channel="email",
        recipient="x@x.com",
        payload={},
    )
    assert row is not None
    await db_session.commit()

    await repo.mark_failed(row.id, "transient error")
    await db_session.commit()

    await repo.mark_success(row.id)
    await db_session.commit()

    refreshed = await repo.get(row.id)
    assert refreshed is not None
    assert refreshed.status == NotificationStatus.SENT.value
    assert refreshed.last_error is None

    await db_session.delete(refreshed)
    await db_session.commit()
