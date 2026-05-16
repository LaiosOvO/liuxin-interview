"""Phase 1 API 全流程集成测试 — 用 InMemorySaver + 内存 Repository。

覆盖：
- POST /api/flows 起流程 → 返回 current_node=manager_review/waiting_human
- GET /api/flows/{id} 返回流程信息
- GET /api/flows/{id}/nodes 返回 apply + manager_review 两个节点
- POST /api/flows/{id}/nodes/{nid}/actions advance → 节点 done + 流程 completed
- 重复 advance 同一节点 → 409
- reject 路径 → 节点 rejected + 流程 rejected
- 双层状态分离：GET /api/flows 只读业务表
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver

from offboarding_flow.api.deps import (
    get_action_repo,
    get_db_session,
    get_flow_repo,
    get_flow_service,
    get_node_repo,
    get_node_service,
)
from offboarding_flow.flow_engine.graph import _build_state_graph, dispose_graph
from offboarding_flow.main import create_app
from offboarding_flow.services import FlowService, NodeService
from offboarding_flow.state_store.enums import (
    ActionStatus,
    FlowStatus,
    NodeStatus,
)

# --------- 内存 Repository（不依赖真 DB） ---------


class _FakeFlow:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id") or uuid.uuid4()
        self.employee_id = kwargs["employee_id"]
        self.template = kwargs.get("template", "standard_offboarding")
        self.status = kwargs.get("status", FlowStatus.IN_PROGRESS.value)
        self.context = kwargs.get("context", {})
        self.started_at = kwargs.get("started_at", datetime.now(UTC))
        self.completed_at = None


class _FakeNode:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id") or uuid.uuid4()
        self.flow_id = kwargs["flow_id"]
        self.node_name = kwargs["node_name"]
        self.node_title = kwargs["node_title"]
        self.status = kwargs["status"]
        self.assignee = kwargs.get("assignee")
        self.result_text = kwargs.get("result_text")
        self.is_overdue = False
        self.entered_at = kwargs.get("entered_at", datetime.now(UTC))
        self.completed_at = None


class _FakeAction:
    def __init__(self, **kwargs):
        self.id = uuid.uuid4()
        self.flow_id = kwargs["flow_id"]
        self.node_state_id = kwargs.get("node_state_id")
        self.actor = kwargs["actor"]
        self.action = kwargs["action"]
        self.result_text = kwargs.get("result_text")
        self.status = kwargs.get("status", ActionStatus.SUCCESS.value)
        self.error_message = kwargs.get("error_message")
        self.payload = kwargs.get("payload")
        self.created_at = datetime.now(UTC)


class FakeFlowRepo:
    def __init__(self, store):
        self.store = store

    async def create(self, employee_id, template="standard_offboarding", context=None):
        flow = _FakeFlow(employee_id=employee_id, template=template, context=context or {})
        self.store["flows"][flow.id] = flow
        return flow

    async def get(self, flow_id):
        return self.store["flows"].get(flow_id)

    async def list_all(self, limit=50):
        return list(self.store["flows"].values())

    async def mark_completed(self, flow_id, status=FlowStatus.COMPLETED):
        flow = self.store["flows"].get(flow_id)
        if flow:
            flow.status = status.value
            flow.completed_at = datetime.now(UTC)

    async def append_node_result(self, flow_id, result):
        """Phase 2 Plan 01：业务侧 node_results 冗余追加。"""
        flow = self.store["flows"].get(flow_id)
        if flow is None:
            return
        context = dict(flow.context or {})
        results = list(context.get("node_results", []))
        results.append(result)
        context["node_results"] = results
        flow.context = context


class FakeNodeRepo:
    def __init__(self, store):
        self.store = store

    async def upsert(self, flow_id, node_name, node_title, status, assignee=None):
        key = (flow_id, node_name)
        existing = self.store["nodes_by_key"].get(key)
        if existing:
            existing.status = status.value
            existing.assignee = assignee
            return existing
        node = _FakeNode(
            flow_id=flow_id,
            node_name=node_name,
            node_title=node_title,
            status=status.value,
            assignee=assignee,
        )
        self.store["nodes"][node.id] = node
        self.store["nodes_by_key"][key] = node
        return node

    async def get(self, node_id):
        return self.store["nodes"].get(node_id)

    async def list_by_flow(self, flow_id):
        return [n for n in self.store["nodes"].values() if n.flow_id == flow_id]

    async def complete(self, node_id, result_text, new_status=NodeStatus.DONE):
        node = self.store["nodes"].get(node_id)
        if node:
            node.status = new_status.value
            node.result_text = result_text
            node.completed_at = datetime.now(UTC)
            return node
        return None


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
        log = _FakeAction(
            flow_id=flow_id,
            actor=actor,
            action=action.value,
            node_state_id=node_state_id,
            result_text=result_text,
            status=status.value,
            payload=payload,
        )
        self.store["actions"].append(log)
        return log

    async def list_by_flow(self, flow_id):
        return [a for a in self.store["actions"] if a.flow_id == flow_id]

    async def mark_failed(self, action_id, error_message):
        """Phase 2 Plan 01：双写失败补偿。"""
        for a in self.store["actions"]:
            if a.id == action_id:
                a.status = ActionStatus.FAILED.value
                a.error_message = error_message
                return

    async def mark_success(self, action_id):
        """Phase 2 Plan 01：双写成功 finalize。"""
        for a in self.store["actions"]:
            if a.id == action_id:
                a.status = ActionStatus.SUCCESS.value
                a.error_message = None
                return

    async def list_failed(self, limit=100, flow_id=None):
        """Phase 2 Plan 01：recover 入口。"""
        items = [a for a in self.store["actions"] if a.status == ActionStatus.FAILED.value]
        if flow_id is not None:
            items = [a for a in items if a.flow_id == flow_id]
        return items[:limit]


class FakeSession:
    """模拟 AsyncSession.commit() — 内存 store 不需要真 commit。"""

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass


# --------- Fixtures ---------


@pytest.fixture
def fake_store():
    return {"flows": {}, "nodes": {}, "nodes_by_key": {}, "actions": []}


@pytest.fixture
def fake_graph():
    """用 InMemorySaver build graph（Plan 04 _build_state_graph）。"""
    saver = InMemorySaver()
    graph = _build_state_graph().compile(checkpointer=saver)
    return graph


@pytest.fixture(autouse=True)
async def _cleanup_graph_singleton():
    """每个测试前后重置 graph 单例（防止跨测试污染）。"""
    await dispose_graph()
    yield
    await dispose_graph()


@pytest.fixture
async def client(fake_store, fake_graph):
    app = create_app()

    fake_session = FakeSession()
    # 共享 store 让 Repository 看到同一份内存
    shared_flow_repo = FakeFlowRepo(fake_store)
    shared_node_repo = FakeNodeRepo(fake_store)
    shared_action_repo = FakeActionRepo(fake_store)

    async def _override_session():
        yield fake_session

    def _override_flow_repo():
        return shared_flow_repo

    def _override_node_repo():
        return shared_node_repo

    def _override_action_repo():
        return shared_action_repo

    def _override_flow_service():
        return FlowService(
            fake_session,
            shared_flow_repo,
            shared_node_repo,
            shared_action_repo,
            fake_graph,
        )

    # Phase 2 Plan 01: session_factory 用 fake — 失败补偿走同一个 fake_session
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_session_factory():
        yield fake_session

    def _override_node_service():
        return NodeService(
            fake_session,
            shared_flow_repo,
            shared_node_repo,
            shared_action_repo,
            fake_graph,
            session_factory=_fake_session_factory,
        )

    app.dependency_overrides[get_db_session] = _override_session
    app.dependency_overrides[get_flow_repo] = _override_flow_repo
    app.dependency_overrides[get_node_repo] = _override_node_repo
    app.dependency_overrides[get_action_repo] = _override_action_repo
    app.dependency_overrides[get_flow_service] = _override_flow_service
    app.dependency_overrides[get_node_service] = _override_node_service

    async with LifespanManager(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


# --------- 测试用例 ---------


async def test_create_flow_returns_manager_review_waiting(client):
    """POST /api/flows 起流程 → 拿到 flow_id + current_node=manager_review/waiting_human。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    data = body["data"]
    assert "flow_id" in data
    assert data["employee_id"] == "zhang.san"
    assert data["status"] == "in_progress"
    assert data["current_node"]["name"] == "manager_review"
    assert data["current_node"]["status"] == "waiting_human"


async def test_get_flow_returns_business_state(client):
    """GET /api/flows/{id} 返回业务表状态。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = resp.json()["data"]["flow_id"]

    resp = await client.get(f"/api/flows/{flow_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["status"] == "in_progress"
    assert body["data"]["node_count"] >= 2


async def test_list_flow_nodes_returns_apply_and_manager_review(client):
    """GET /api/flows/{id}/nodes 列 apply + manager_review。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    flow_id = resp.json()["data"]["flow_id"]

    resp = await client.get(f"/api/flows/{flow_id}/nodes")
    assert resp.status_code == 200
    nodes = resp.json()["data"]
    names = sorted(n["name"] for n in nodes)
    assert names == ["apply", "manager_review"]


async def test_advance_action_completes_manager_review_node(client):
    """POST /actions advance → manager_review done + 流程继续推进到 hr_initial（Phase 2 拓扑）。

    Phase 1 简化拓扑：manager_review 是末节点，advance 后 flow=completed。
    Phase 2 完整拓扑：manager_review advance 后流程推进到 hr_initial，flow 仍 in_progress。
    """
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    data = resp.json()["data"]
    flow_id = data["flow_id"]
    node_id = data["current_node"]["id"]

    resp = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": "同意离职", "actor": "li.si"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["new_status"] == "done"
    assert body["data"]["current_action"] == "advance"
    # Phase 2 manager_review 不再是末节点 — flow 仍 in_progress
    assert body["data"]["flow_status"] == "in_progress"

    # 二次校验 GET — manager_review done + result_text 写入
    resp = await client.get(f"/api/flows/{flow_id}/nodes")
    nodes = resp.json()["data"]
    mr = next(n for n in nodes if n["name"] == "manager_review")
    assert mr["status"] == "done"
    assert mr["result_text"] == "同意离职"


async def test_reject_action_marks_node_rejected(client):
    """POST /actions reject → manager_review rejected + flow rejected。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    data = resp.json()["data"]
    flow_id = data["flow_id"]
    node_id = data["current_node"]["id"]

    resp = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "reject", "result_text": "条件不符", "actor": "li.si"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["new_status"] == "rejected"
    assert body["data"]["flow_status"] == "rejected"


async def test_duplicate_advance_returns_409(client):
    """重复 advance 同一节点 → 409 conflict。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    data = resp.json()["data"]
    flow_id = data["flow_id"]
    node_id = data["current_node"]["id"]

    # 第一次 advance
    await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": "同意", "actor": "li.si"},
    )
    # 第二次 advance — 期望 409
    resp = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "advance", "result_text": "再次同意", "actor": "li.si"},
    )
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["success"] is False


async def test_unknown_flow_returns_404(client):
    random_id = uuid.uuid4()
    resp = await client.get(f"/api/flows/{random_id}")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


async def test_invalid_action_value_returns_422(client):
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    data = resp.json()["data"]
    flow_id = data["flow_id"]
    node_id = data["current_node"]["id"]

    resp = await client.post(
        f"/api/flows/{flow_id}/nodes/{node_id}/actions",
        json={"action": "nonexistent", "result_text": "x", "actor": "li.si"},
    )
    assert resp.status_code == 422


async def test_missing_employee_id_returns_422(client):
    resp = await client.post("/api/flows", json={})
    assert resp.status_code == 422


async def test_envelope_shape_on_create_flow(client):
    """所有响应必须是 envelope shape。"""
    resp = await client.post("/api/flows", json={"employee_id": "zhang.san"})
    body = resp.json()
    assert set(body.keys()) == {"success", "data", "error", "meta"}
    assert body["error"] is None
