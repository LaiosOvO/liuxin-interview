"""test_flow_full_chain.py — 真 PG + 真 PostgresSaver 双层一致性集成测试。

CLAUDE.md §2.3：集成测试禁止 mock DB。
本测试要 TEST_DATABASE_URL 设置（指向 offboarding_test schema）。
"""

from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="需要 TEST_DATABASE_URL 指向 offboarding_test DB",
    ),
]


@pytest.fixture
async def services():
    """构建真 PG 的 service 套件 — 业务表 + LangGraph checkpoint 都用真 DB。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from offboarding_flow.flow_engine.graph import build_graph, dispose_graph
    from offboarding_flow.services import FlowService, NodeService
    from offboarding_flow.state_store.models import Base
    from offboarding_flow.state_store.repositories import (
        ActionRepository,
        FlowRepository,
        NodeRepository,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(dsn, echo=False)

    # 创建 schema（drop + recreate）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, expire_on_commit=False)

    # 真 graph + PostgresSaver
    graph = await build_graph(use_memory_saver=False)

    @asynccontextmanager
    async def sf():
        async with maker() as s:
            yield s

    async with maker() as session:
        flow_repo = FlowRepository(session)
        node_repo = NodeRepository(session)
        action_repo = ActionRepository(session)
        flow_svc = FlowService(session, flow_repo, node_repo, action_repo, graph)
        node_svc = NodeService(
            session, flow_repo, node_repo, action_repo, graph, session_factory=sf
        )
        yield {
            "session": session,
            "flow_svc": flow_svc,
            "node_svc": node_svc,
            "graph": graph,
        }

    await dispose_graph()
    await engine.dispose()


async def test_create_flow_writes_business_and_checkpoint(services):
    """create_flow 后业务表 + LangGraph checkpoint 都有数据。"""
    flow_svc = services["flow_svc"]
    graph = services["graph"]

    created = await flow_svc.create_flow(employee_id="zhang.san")
    flow_id = uuid.UUID(created["flow_id"])

    # 业务表：flow_instances + node_states 应有
    flow = await services["flow_svc"].get_flow(flow_id)
    assert flow is not None
    assert flow["employee_id"] == "zhang.san"
    assert flow["node_count"] >= 2  # apply + manager_review

    # LangGraph checkpoint：snapshot 存在
    snapshot = await graph.aget_state({"configurable": {"thread_id": str(flow_id)}})
    assert snapshot is not None
    # interrupt 在 manager_review
    assert snapshot.next == ("manager_review",)


async def test_advance_writes_node_results_to_context(services):
    """advance manager_review → flow.context.node_results 含本节点。"""
    flow_svc = services["flow_svc"]
    node_svc = services["node_svc"]

    created = await flow_svc.create_flow(employee_id="zhang.san")
    flow_id = uuid.UUID(created["flow_id"])
    manager_node_id = uuid.UUID(created["current_node"]["id"])

    await node_svc.submit_action(
        flow_id=flow_id,
        node_id=manager_node_id,
        action="advance",
        result_text="同意",
        actor="li.si",
    )

    # context.node_results 应含 manager_review
    flow = await services["flow_svc"].flow_repo.get(flow_id)
    assert flow is not None
    results = (flow.context or {}).get("node_results", [])
    assert any(
        r.get("node_name") == "manager_review" for r in results
    ), f"node_results 应含 manager_review，实际 {results}"
