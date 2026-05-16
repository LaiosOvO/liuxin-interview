"""test_auto_node_service.py — AutoNodeService 双写单测（Phase 4.5）。

用 fake/mock session 不连真 DB。集成测试（Plan 02）才连真 PG。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.services.auto_node_service import AutoNodeService
from offboarding_flow.state_store.enums import ActionStatus


@pytest.fixture
def fake_session_factory():
    """造 fake session_factory — 返回 mock AsyncSession，记录 commit 次数。"""
    captured: dict = {"sessions": [], "commits": 0}

    @asynccontextmanager
    async def factory():
        sess = MagicMock()

        async def _commit():
            captured["commits"] += 1

        sess.commit = _commit
        sess.rollback = AsyncMock()
        sess.execute = AsyncMock()
        sess.flush = AsyncMock()
        captured["sessions"].append(sess)
        yield sess

    return factory, captured


async def test_execute_auto_action_success_does_three_writes(fake_session_factory, monkeypatch):
    """SUCCESS path：upsert node_states + INSERT action_log + append flow.context.node_results；最后 commit。"""
    factory, captured = fake_session_factory
    svc = AutoNodeService(session_factory=factory)

    upserts: list = []
    creates: list = []
    appends: list = []

    async def fake_upsert(**kw):
        upserts.append(kw)
        return MagicMock()

    async def fake_create(**kw):
        creates.append(kw)
        return MagicMock()

    async def fake_append(**kw):
        appends.append(kw)

    from offboarding_flow.services import auto_node_service as mod

    monkeypatch.setattr(mod, "NodeRepository", lambda s: MagicMock(upsert=fake_upsert))
    monkeypatch.setattr(mod, "ActionRepository", lambda s: MagicMock(create=fake_create))
    monkeypatch.setattr(mod, "FlowRepository", lambda s: MagicMock(append_node_result=fake_append))

    flow_id = uuid.uuid4()
    await svc.execute_auto_action(
        flow_id=flow_id,
        node_name="auto_archive_to_storage",
        node_title="自动归档（外部存储）",
        result_text="done",
        action_status=ActionStatus.SUCCESS,
        payload={"foo": "bar"},
    )
    assert len(upserts) == 1
    assert upserts[0]["node_name"] == "auto_archive_to_storage"
    assert upserts[0]["assignee"] == "system:auto"
    assert len(creates) == 1
    assert creates[0]["actor"] == "system:auto"
    assert len(appends) == 1
    assert appends[0]["result"]["actor"] == "system:auto"
    assert captured["commits"] == 1  # 一次 commit


async def test_execute_auto_action_failed_only_action_log(fake_session_factory, monkeypatch):
    """FAILED path：仅 INSERT action_log（失败），不动 node_states / context.node_results。"""
    factory, captured = fake_session_factory
    svc = AutoNodeService(session_factory=factory)

    upserts: list = []
    creates: list = []
    appends: list = []

    async def fake_upsert(**kw):
        upserts.append(kw)

    async def fake_create(**kw):
        creates.append(kw)
        return MagicMock()

    async def fake_append(**kw):
        appends.append(kw)

    from offboarding_flow.services import auto_node_service as mod

    monkeypatch.setattr(mod, "NodeRepository", lambda s: MagicMock(upsert=fake_upsert))
    monkeypatch.setattr(mod, "ActionRepository", lambda s: MagicMock(create=fake_create))
    monkeypatch.setattr(mod, "FlowRepository", lambda s: MagicMock(append_node_result=fake_append))

    await svc.execute_auto_action(
        flow_id=uuid.uuid4(),
        node_name="auto_archive_to_storage",
        node_title="自动归档",
        action_status=ActionStatus.FAILED,
        error_message="mock service down",
        payload={"url": "http://mock"},
    )
    assert upserts == []
    assert appends == []
    assert len(creates) == 1
    assert creates[0]["status"] == ActionStatus.FAILED
    assert creates[0]["error_message"] == "mock service down"


async def test_default_actor_is_system_auto(fake_session_factory, monkeypatch):
    """不传 actor 时应回退到 system:auto。"""
    factory, _ = fake_session_factory
    svc = AutoNodeService(session_factory=factory)

    creates: list = []

    async def fake_upsert(**kw):
        return MagicMock()

    async def fake_create(**kw):
        creates.append(kw)
        return MagicMock()

    async def fake_append(**kw):
        pass

    from offboarding_flow.services import auto_node_service as mod

    monkeypatch.setattr(mod, "NodeRepository", lambda s: MagicMock(upsert=fake_upsert))
    monkeypatch.setattr(mod, "ActionRepository", lambda s: MagicMock(create=fake_create))

    async def _noop_append(**kw):
        return None

    monkeypatch.setattr(
        mod,
        "FlowRepository",
        lambda s: MagicMock(append_node_result=_noop_append),
    )

    await svc.execute_auto_action(
        flow_id=uuid.uuid4(),
        node_name="x",
        node_title="X",
    )
    assert creates[0]["actor"] == "system:auto"
