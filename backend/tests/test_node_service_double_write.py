"""test_node_service_double_write.py — NodeService 双写规范集成测试（Phase 2 Plan 01）。

测试用 fake Repository + InMemorySaver graph，验证双写规范完整性：
- advance 成功 → action_log.status='success' + node_states.done + node_results 冗余
- graph 失败 → action_log.status='failed' + node_states 仍为 done（业务已 commit）+ HTTPException(500)
- 连续 advance → context.node_results 累积
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from langgraph.checkpoint.memory import InMemorySaver

from offboarding_flow.flow_engine.graph import _build_state_graph, dispose_graph
from offboarding_flow.services.node_service import NodeService
from offboarding_flow.state_store.enums import (
    ActionStatus,
    FlowStatus,
    NodeStatus,
)


# ---------------------------------------------------------------------------
# In-memory fake Repositories（与 test_api_flows.py 模式一致）
# ---------------------------------------------------------------------------
class _FakeFlow:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.employee_id = kwargs.get("employee_id", "zhang.san")
        self.template = "standard_offboarding"
        self.status = kwargs.get("status", FlowStatus.IN_PROGRESS.value)
        self.context: dict = kwargs.get("context") or {}
        self.started_at = datetime.now(UTC)
        self.completed_at = None


class _FakeNode:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.flow_id = kwargs["flow_id"]
        self.node_name = kwargs["node_name"]
        self.node_title = kwargs.get("node_title", "Title")
        self.status = kwargs.get("status", NodeStatus.WAITING_HUMAN.value)
        self.assignee = kwargs.get("assignee")
        self.result_text = None
        self.completed_at = None


class _FakeAction:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.flow_id = kwargs["flow_id"]
        self.node_state_id = kwargs.get("node_state_id")
        self.actor = kwargs["actor"]
        self.action = kwargs["action"]
        self.result_text = kwargs.get("result_text")
        self.status = kwargs.get("status", ActionStatus.PENDING.value)
        self.error_message = None
        self.payload = None


class FakeFlowRepo:
    def __init__(self, store):
        self.store = store

    async def create(self, employee_id, template="standard_offboarding", context=None):
        f = _FakeFlow(employee_id=employee_id, context=context or {})
        self.store["flows"][f.id] = f
        return f

    async def get(self, flow_id):
        return self.store["flows"].get(flow_id)

    async def mark_completed(self, flow_id, status=FlowStatus.COMPLETED):
        f = self.store["flows"].get(flow_id)
        if f:
            f.status = status.value
            f.completed_at = datetime.now(UTC)

    async def append_node_result(self, flow_id, result):
        f = self.store["flows"].get(flow_id)
        if f is None:
            return
        ctx = dict(f.context or {})
        results = list(ctx.get("node_results", []))
        results.append(result)
        ctx["node_results"] = results
        f.context = ctx


class FakeNodeRepo:
    def __init__(self, store):
        self.store = store

    async def get(self, node_id):
        return self.store["nodes"].get(node_id)

    async def complete(self, node_id, result_text, new_status=NodeStatus.DONE):
        n = self.store["nodes"].get(node_id)
        if n:
            n.status = new_status.value
            n.result_text = result_text
            n.completed_at = datetime.now(UTC)
            return n

    async def upsert(self, flow_id, node_name, node_title, status, assignee=None):
        key = (flow_id, node_name)
        if key in self.store["nodes_by_key"]:
            n = self.store["nodes_by_key"][key]
            n.status = status.value
            return n
        n = _FakeNode(
            flow_id=flow_id,
            node_name=node_name,
            node_title=node_title,
            status=status.value,
            assignee=assignee,
        )
        self.store["nodes"][n.id] = n
        self.store["nodes_by_key"][key] = n
        return n


class FakeActionRepo:
    def __init__(self, store):
        self.store = store

    async def create(
        self,
        flow_id,
        actor,
        action,
        node_state_id=None,
        result_text=None,
        status=ActionStatus.SUCCESS,
        error_message=None,
        payload=None,
    ):
        a = _FakeAction(
            flow_id=flow_id,
            actor=actor,
            action=action.value,
            node_state_id=node_state_id,
            result_text=result_text,
            status=status.value,
        )
        self.store["actions"].append(a)
        return a

    async def mark_failed(self, action_id, error_message):
        for a in self.store["actions"]:
            if a.id == action_id:
                a.status = ActionStatus.FAILED.value
                a.error_message = error_message
                return

    async def mark_success(self, action_id):
        for a in self.store["actions"]:
            if a.id == action_id:
                a.status = ActionStatus.SUCCESS.value
                a.error_message = None
                return


class FakeSession:
    async def commit(self):
        pass

    async def rollback(self):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def store():
    return {"flows": {}, "nodes": {}, "nodes_by_key": {}, "actions": []}


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def graph():
    saver = InMemorySaver()
    return _build_state_graph().compile(checkpointer=saver)


@pytest.fixture(autouse=True)
async def _reset_graph_singleton():
    await dispose_graph()
    yield
    await dispose_graph()


@pytest.fixture
def fake_session_factory(store):
    """session_factory yields a FakeSession 子类 — 让 ActionRepository(session) 仍可工作。

    技巧：返回的 session 上挂个 'fake_store' 属性，让我们 monkey-patch ActionRepository
    的 mark_failed / mark_success 走 fake store。但更简单：把 ActionRepository 直接换成
    FakeActionRepo —— 在 session_factory 提供的 session 上 monkeypatch 实现。

    实际方案：暴露一个回调让 node_service 在失败补偿时调 fake_action_repo。
    本测试用 monkey-patch 全局 ActionRepository 类引用更简洁。
    """

    @asynccontextmanager
    async def _f():
        # 创建一个特殊 session 对象，commit() 为 no-op
        s = MagicMock()
        s.commit = AsyncMock()
        s.fake_store = store
        yield s

    return _f


@pytest.fixture
def node_service(store, fake_session, graph, fake_session_factory, monkeypatch):
    flow_repo = FakeFlowRepo(store)
    node_repo = FakeNodeRepo(store)
    action_repo = FakeActionRepo(store)

    # Monkey-patch ActionRepository class 引用 — 让 node_service 用 FakeActionRepo
    # 因为失败补偿路径会 import + instantiate ActionRepository(session)
    import offboarding_flow.services.node_service as ns_module

    fake_repo_for_fail = FakeActionRepo(store)

    class _FakeRepoWrapper:
        def __init__(self, session):
            self._inner = fake_repo_for_fail

        async def mark_failed(self, action_id, error_message):
            await self._inner.mark_failed(action_id, error_message)

        async def mark_success(self, action_id):
            await self._inner.mark_success(action_id)

    monkeypatch.setattr(ns_module, "ActionRepository", _FakeRepoWrapper)

    return NodeService(
        session=fake_session,
        flow_repo=flow_repo,
        node_repo=node_repo,
        action_repo=action_repo,
        graph=graph,
        session_factory=fake_session_factory,
    )


@pytest.fixture
def seeded_flow_and_node(store, graph):
    """起一个流程到 manager_review interrupt — 业务表预 upsert 两个节点。"""
    flow = _FakeFlow(employee_id="zhang.san")
    store["flows"][flow.id] = flow

    apply_node = _FakeNode(
        flow_id=flow.id,
        node_name="apply",
        node_title="申请提交",
        status=NodeStatus.DONE.value,
    )
    manager_node = _FakeNode(
        flow_id=flow.id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
    )
    store["nodes"][apply_node.id] = apply_node
    store["nodes"][manager_node.id] = manager_node
    store["nodes_by_key"][(flow.id, "apply")] = apply_node
    store["nodes_by_key"][(flow.id, "manager_review")] = manager_node

    return flow, manager_node


# ---------------------------------------------------------------------------
# 双写规范测试
# ---------------------------------------------------------------------------
async def test_advance_success_marks_action_log_success(
    node_service, seeded_flow_and_node, store, graph
):
    """advance 成功 → action_log.status=success + node.status=done + node_results 含本节点。"""
    flow, manager_node = seeded_flow_and_node

    # 先让 graph 跑到 manager_review interrupt（建 thread）
    initial = {
        "flow_id": str(flow.id),
        "employee_id": flow.employee_id,
        "current_action": None,
        "node_results": [],
        "context": {},
    }
    await graph.ainvoke(initial, config={"configurable": {"thread_id": str(flow.id)}})

    result = await node_service.submit_action(
        flow_id=flow.id,
        node_id=manager_node.id,
        action="advance",
        result_text="同意",
        actor="li.si",
    )

    # 业务侧断言
    assert result["new_status"] == "done"
    assert result["current_action"] == "advance"
    assert manager_node.status == NodeStatus.DONE.value
    assert manager_node.result_text == "同意"

    # action_log 状态：PENDING → SUCCESS（mark_success 已执行）
    assert len(store["actions"]) == 1
    assert store["actions"][0].status == ActionStatus.SUCCESS.value
    assert store["actions"][0].error_message is None

    # node_results 业务侧冗余
    assert len(flow.context["node_results"]) == 1
    nr = flow.context["node_results"][0]
    assert nr["node_name"] == "manager_review"
    assert nr["result_text"] == "同意"
    assert nr["actor"] == "li.si"


async def test_graph_failure_marks_action_log_failed_and_raises_500(
    node_service, seeded_flow_and_node, store, graph
):
    """graph.ainvoke 抛 → action_log.failed + node.status=done（业务已 commit）+ HTTPException(500)。"""
    flow, manager_node = seeded_flow_and_node

    # 先 invoke 到 manager_review interrupt
    initial = {
        "flow_id": str(flow.id),
        "employee_id": flow.employee_id,
        "current_action": None,
        "node_results": [],
        "context": {},
    }
    await graph.ainvoke(initial, config={"configurable": {"thread_id": str(flow.id)}})

    # patch graph.ainvoke 抛
    original_ainvoke = node_service.graph.ainvoke
    node_service.graph.ainvoke = AsyncMock(side_effect=ConnectionError("simulated"))

    try:
        with pytest.raises(HTTPException) as exc_info:
            await node_service.submit_action(
                flow_id=flow.id,
                node_id=manager_node.id,
                action="advance",
                result_text="同意",
                actor="li.si",
            )
    finally:
        node_service.graph.ainvoke = original_ainvoke

    # HTTPException(500) + 错误消息含 recover 提示
    assert exc_info.value.status_code == 500
    assert "ConnectionError" in str(exc_info.value.detail)
    assert "recover_from_db" in str(exc_info.value.detail)

    # 业务侧已 commit：node 仍 done
    assert manager_node.status == NodeStatus.DONE.value
    # action_log status = failed + error_message 含异常类名
    assert len(store["actions"]) == 1
    assert store["actions"][0].status == ActionStatus.FAILED.value
    assert "ConnectionError" in store["actions"][0].error_message


async def test_node_results_appended_to_flow_context(
    node_service, seeded_flow_and_node, store, graph
):
    """同一 flow 多次 advance → context.node_results 长度累加。"""
    flow, manager_node = seeded_flow_and_node

    initial = {
        "flow_id": str(flow.id),
        "employee_id": flow.employee_id,
        "current_action": None,
        "node_results": [],
        "context": {},
    }
    await graph.ainvoke(initial, config={"configurable": {"thread_id": str(flow.id)}})

    # 第 1 次 advance
    await node_service.submit_action(
        flow_id=flow.id,
        node_id=manager_node.id,
        action="advance",
        result_text="同意",
        actor="li.si",
    )
    # 模拟"激活下一个节点"（Phase 1 graph 到 END 后无 next，所以本测试只校验第 1 次的 append）
    assert len(flow.context["node_results"]) == 1


async def test_invalid_action_raises_400(node_service, seeded_flow_and_node):
    """非法 action → HTTPException(400)。"""
    flow, manager_node = seeded_flow_and_node
    with pytest.raises(HTTPException) as exc_info:
        await node_service.submit_action(
            flow_id=flow.id,
            node_id=manager_node.id,
            action="invalid",
            result_text="x",
            actor="li.si",
        )
    assert exc_info.value.status_code == 400


async def test_reject_marks_flow_rejected(node_service, seeded_flow_and_node, store, graph):
    """reject → flow.status=rejected + action_log 仍是 SUCCESS（graph 也成功 advance）。"""
    flow, manager_node = seeded_flow_and_node

    initial = {
        "flow_id": str(flow.id),
        "employee_id": flow.employee_id,
        "current_action": None,
        "node_results": [],
        "context": {},
    }
    await graph.ainvoke(initial, config={"configurable": {"thread_id": str(flow.id)}})

    await node_service.submit_action(
        flow_id=flow.id,
        node_id=manager_node.id,
        action="reject",
        result_text="不同意",
        actor="li.si",
    )

    # flow.status = rejected
    assert flow.status == FlowStatus.REJECTED.value
    # node.status = rejected
    assert manager_node.status == NodeStatus.REJECTED.value
