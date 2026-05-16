"""单元测试：workers.timeout_scan（NOTI-05 + TIMEOUT-01 — Phase 6）。

测试矩阵：
1. compute_sla_hours：演示模式 override / prod 模式忽略 override / 默认 24h
2. compute_threshold：阈值边界（含正好相等不算超时）
3. find_overdue_nodes：SQL where 条件正确（status='waiting_human' + entered_at < threshold）
4. scan_once：找到 + 入队 + 写 action_log + 幂等防重发
5. TimeoutScanWorker：start/stop 优雅停止

策略：mock OutboxRepository + UserRepository + session.execute — 不依赖真 DB。
真集成测试（与 outbox_drain 串联）留 integration/ 目录。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from offboarding_flow.workers.timeout_scan import (
    TIMEOUT_REMIND_ACTION,
    TimeoutScanWorker,
    _build_timeout_reminder_payload,
    compute_sla_hours,
    compute_threshold,
    enqueue_timeout_reminders,
    find_overdue_nodes,
    scan_once,
)


# ---------------------------------------------------------------------------
# 公用 fixture
# ---------------------------------------------------------------------------
def _make_settings(
    *,
    app_mode: str = "demo",
    node_timeout_hours: float = 24.0,
    demo_timeout_override_hours: float | None = None,
    interval: float = 60.0,
) -> SimpleNamespace:
    s = SimpleNamespace()
    s.app_mode = app_mode
    s.node_timeout_hours = node_timeout_hours
    s.demo_timeout_override_hours = demo_timeout_override_hours
    s.timeout_scan_interval_seconds = interval
    s.is_demo = app_mode == "demo"
    s.demo_inbox = "1624456575@qq.com"
    return s


def _make_node(
    *,
    node_id: uuid.UUID | None = None,
    flow_id: uuid.UUID | None = None,
    status: str = "waiting_human",
    entered_at: datetime | None = None,
    is_overdue: bool = False,
    assignee: str | None = "li.si",
    node_title: str = "上级审批",
):
    """构造 fake NodeState（不依赖 ORM 实例）。"""
    node = MagicMock()
    node.id = node_id or uuid.uuid4()
    node.flow_id = flow_id or uuid.uuid4()
    node.status = status
    node.entered_at = entered_at
    node.is_overdue = is_overdue
    node.assignee = assignee
    node.node_title = node_title
    node.node_name = "manager_review"
    return node


# ---------------------------------------------------------------------------
# 1. compute_sla_hours — 优先级 / 默认值
# ---------------------------------------------------------------------------
class TestComputeSlaHours:
    def test_default_24h_when_no_override(self):
        s = _make_settings(app_mode="demo", demo_timeout_override_hours=None)
        assert compute_sla_hours(s) == 24.0

    def test_demo_override_takes_precedence(self):
        s = _make_settings(
            app_mode="demo",
            node_timeout_hours=24.0,
            demo_timeout_override_hours=0.05,
        )
        assert compute_sla_hours(s) == 0.05

    def test_prod_mode_ignores_demo_override(self):
        """prod 模式必须忽略 DEMO_TIMEOUT_OVERRIDE_HOURS，永远走 NODE_TIMEOUT_HOURS。"""
        s = _make_settings(
            app_mode="prod",
            node_timeout_hours=24.0,
            demo_timeout_override_hours=0.05,
        )
        assert compute_sla_hours(s) == 24.0

    def test_custom_node_timeout(self):
        s = _make_settings(app_mode="prod", node_timeout_hours=48.0)
        assert compute_sla_hours(s) == 48.0

    def test_demo_override_zero_edge_case(self):
        """DEMO_TIMEOUT_OVERRIDE_HOURS=0 → 一切都超时（边界）。"""
        s = _make_settings(app_mode="demo", demo_timeout_override_hours=0.0)
        assert compute_sla_hours(s) == 0.0


# ---------------------------------------------------------------------------
# 2. compute_threshold — 阈值时间戳计算 + 边界
# ---------------------------------------------------------------------------
class TestComputeThreshold:
    def test_threshold_24h_ago(self):
        s = _make_settings(node_timeout_hours=24.0, demo_timeout_override_hours=None)
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        threshold = compute_threshold(s, now=now)
        assert threshold == datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)

    def test_threshold_demo_override_3min(self):
        s = _make_settings(app_mode="demo", demo_timeout_override_hours=0.05)
        now = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
        threshold = compute_threshold(s, now=now)
        # 0.05h = 180s = 3min
        assert threshold == now - timedelta(seconds=180)

    def test_threshold_uses_now_default(self):
        """不传 now → 用 datetime.now(UTC)（接近当前）。"""
        s = _make_settings(node_timeout_hours=24.0)
        before = datetime.now(UTC)
        threshold = compute_threshold(s)
        after = datetime.now(UTC)
        # threshold 应在 [before - 24h, after - 24h] 区间
        assert before - timedelta(hours=24) <= threshold <= after - timedelta(hours=24)


# ---------------------------------------------------------------------------
# 3. find_overdue_nodes — SQL 查询条件 + limit
# ---------------------------------------------------------------------------
class TestFindOverdueNodes:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_overdue(self):
        s = _make_settings(node_timeout_hours=24.0)
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        nodes = await find_overdue_nodes(session, s)
        assert nodes == []
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_overdue_nodes(self):
        s = _make_settings(node_timeout_hours=24.0)
        session = MagicMock()
        overdue_node = _make_node(entered_at=datetime.now(UTC) - timedelta(hours=25))
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [overdue_node]
        session.execute = AsyncMock(return_value=result_mock)

        nodes = await find_overdue_nodes(session, s)
        assert len(nodes) == 1
        assert nodes[0] is overdue_node


# ---------------------------------------------------------------------------
# 4. enqueue_timeout_reminders + scan_once — 业务流程
# ---------------------------------------------------------------------------
class TestEnqueueTimeoutReminders:
    @pytest.mark.asyncio
    async def test_enqueue_for_overdue_node(self):
        """超时节点：标记 is_overdue + enqueue outbox + 写 action_log。"""
        s = _make_settings()
        session = MagicMock()
        session.add = MagicMock()
        session.get = AsyncMock(return_value=SimpleNamespace(employee_id="zhang.san"))
        # _mark_overdue: session.execute UPDATE
        # _has_been_reminded: session.execute SELECT
        execute_mock = AsyncMock()
        # _has_been_reminded 返回 None（未发过）
        not_reminded_result = MagicMock()
        not_reminded_result.scalar_one_or_none.return_value = None
        execute_mock.return_value = not_reminded_result
        session.execute = execute_mock

        node = _make_node(
            entered_at=datetime.now(UTC) - timedelta(hours=25),
            assignee="li.si",
        )

        # mock UserRepository + OutboxRepository
        outbox_row = SimpleNamespace(id=uuid.uuid4())
        with (
            patch(
                "offboarding_flow.workers.timeout_scan.UserRepository",
            ) as UserCls,
            patch(
                "offboarding_flow.workers.timeout_scan.OutboxRepository",
            ) as OutboxCls,
        ):
            user_repo = UserCls.return_value
            user_repo.get_by_username = AsyncMock(
                return_value=SimpleNamespace(email="li.si@demo.local")
            )
            outbox_repo = OutboxCls.return_value
            outbox_repo.enqueue = AsyncMock(return_value=outbox_row)

            count = await enqueue_timeout_reminders(session, [node], s)

        assert count == 1
        outbox_repo.enqueue.assert_called_once()
        call_kwargs = outbox_repo.enqueue.call_args.kwargs
        assert call_kwargs["channel"] == "email"
        assert call_kwargs["recipient"] == "li.si@demo.local"
        # node_state_id=None 避开 UNIQUE 与首次通知冲突
        assert call_kwargs["node_state_id"] is None
        # action_log 落库
        session.add.assert_called_once()
        added = session.add.call_args.args[0]
        assert added.action == TIMEOUT_REMIND_ACTION
        assert added.actor == "system:timeout_scan"

    @pytest.mark.asyncio
    async def test_skip_already_reminded(self):
        """已发过提醒的节点不重复入队（幂等）。"""
        s = _make_settings()
        session = MagicMock()
        session.add = MagicMock()
        already_reminded_result = MagicMock()
        already_reminded_result.scalar_one_or_none.return_value = uuid.uuid4()  # 找到记录
        session.execute = AsyncMock(return_value=already_reminded_result)

        node = _make_node(entered_at=datetime.now(UTC) - timedelta(hours=25))

        with (
            patch("offboarding_flow.workers.timeout_scan.UserRepository"),
            patch("offboarding_flow.workers.timeout_scan.OutboxRepository") as OutboxCls,
        ):
            outbox_repo = OutboxCls.return_value
            outbox_repo.enqueue = AsyncMock()
            count = await enqueue_timeout_reminders(session, [node], s)

        assert count == 0
        outbox_repo.enqueue.assert_not_called()
        # action_log 也不应被加（因为整个节点被 skip）
        session.add.assert_not_called()

    def test_payload_schema_compatible_with_outbox_drain(self):
        """payload 字段必须对齐 outbox_drain._envelope_from_payload 的读取约定。

        outbox_drain 读: subject / html / text / role / username
        """
        node = _make_node(
            entered_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC),
            assignee="li.si",
            node_title="上级审批",
        )
        flow = SimpleNamespace(employee_id="zhang.san")
        payload = _build_timeout_reminder_payload(node, flow)
        # 关键字段（与 outbox_drain.py:_envelope_from_payload 对齐）
        assert "subject" in payload
        assert "html" in payload
        assert "text" in payload
        assert "role" in payload
        assert "username" in payload
        # 标题包含 [超时提醒] 前缀
        assert "[超时提醒]" in payload["subject"]
        assert "上级审批" in payload["subject"]
        assert "zhang.san" in payload["subject"]
        # 元信息
        assert payload["event"] == "timeout_reminder"
        assert payload["node_state_id"] == str(node.id)


# ---------------------------------------------------------------------------
# 5. scan_once — 端到端组合
# ---------------------------------------------------------------------------
class TestScanOnce:
    @pytest.mark.asyncio
    async def test_no_overdue_returns_zero(self):
        s = _make_settings()
        session = MagicMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)
        found, reminded = await scan_once(session, s)
        assert found == 0
        assert reminded == 0

    @pytest.mark.asyncio
    async def test_overdue_triggers_reminder(self):
        s = _make_settings()
        session = MagicMock()
        session.add = MagicMock()
        session.get = AsyncMock(return_value=SimpleNamespace(employee_id="zhang.san"))

        # 两次 execute 调用：1. find_overdue_nodes (SELECT) 2. _mark_overdue (UPDATE) 3. _has_been_reminded (SELECT)
        # 用 side_effect 顺序返回不同 mock
        overdue_node = _make_node(entered_at=datetime.now(UTC) - timedelta(hours=25))
        find_result = MagicMock()
        find_result.scalars.return_value.all.return_value = [overdue_node]
        update_result = MagicMock()  # UPDATE 不查 scalars
        not_reminded_result = MagicMock()
        not_reminded_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(side_effect=[find_result, update_result, not_reminded_result])

        with (
            patch(
                "offboarding_flow.workers.timeout_scan.UserRepository",
            ) as UserCls,
            patch(
                "offboarding_flow.workers.timeout_scan.OutboxRepository",
            ) as OutboxCls,
        ):
            UserCls.return_value.get_by_username = AsyncMock(
                return_value=SimpleNamespace(email="li.si@demo.local")
            )
            OutboxCls.return_value.enqueue = AsyncMock(
                return_value=SimpleNamespace(id=uuid.uuid4())
            )
            found, reminded = await scan_once(session, s)

        assert found == 1
        assert reminded == 1


# ---------------------------------------------------------------------------
# 6. TimeoutScanWorker — start/stop 生命周期
# ---------------------------------------------------------------------------
class TestTimeoutScanWorker:
    @pytest.mark.asyncio
    async def test_stop_event_breaks_loop_quickly(self):
        """stop() 必须让 worker 在 ≤ 1s 内退出（不是等满 interval）。"""
        s = _make_settings(interval=60.0)  # 长 interval 验证 stop 优先级
        worker = TimeoutScanWorker(s)

        # mock _safe_scan 不做事
        worker._safe_scan = AsyncMock()  # type: ignore[method-assign]

        task = asyncio.create_task(worker.run())
        # 给 worker 进入第一次 _sleep_or_stop
        await asyncio.sleep(0.05)
        await worker.stop()
        # 必须在 ≤ 1s 内退出
        await asyncio.wait_for(task, timeout=1.0)

    @pytest.mark.asyncio
    async def test_safe_scan_swallows_exception(self):
        """单次 scan 抛错不应让 worker 崩溃。"""
        s = _make_settings()
        worker = TimeoutScanWorker(s)

        with patch("offboarding_flow.workers.timeout_scan.new_session") as new_session_mock:
            # context manager 进入抛异常
            new_session_mock.side_effect = RuntimeError("DB down")
            # 不抛 — _safe_scan 必须吞掉
            await worker._safe_scan(cycle=1)


# ---------------------------------------------------------------------------
# 7. Integration 占位 — 真 DB + 时间注入（先 skip，留给后续）
# ---------------------------------------------------------------------------
@pytest.mark.skip(reason="集成测试需 testcontainers postgres，留待 Phase 6 后续 / 演示验证")
@pytest.mark.asyncio
async def test_integration_real_db_timeout_scan_end_to_end():
    """端到端：起 flow → entered_at 注入过去 → scan_once → 验 is_overdue=True + outbox 有 row。"""
    pass
