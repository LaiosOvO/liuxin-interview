"""节点状态变更 hook 集成测试 — 真 PG + 真 Redis。

验收 ROADMAP §Phase 3 Success Criteria #3：
节点 advance/reject/return 后该 node 所有未消费 token 立即失效（再 exchange 401）。
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.auth import jti_service
from offboarding_flow.flow_engine.graph import get_graph
from offboarding_flow.services.node_service import NodeService
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
)

pytestmark = pytest.mark.asyncio


async def _seed_token_and_register(redis, node_id, jti: str) -> None:
    """造一个已 consume + registered 的 token。"""
    await jti_service.consume_jti(redis, jti, ttl_seconds=3600)
    await jti_service.register_node_token(redis, node_id, jti, ttl_seconds=3600)


def _make_service(session: AsyncSession, redis) -> NodeService:
    graph = get_graph()
    return NodeService(
        session=session,
        flow_repo=FlowRepository(session),
        node_repo=NodeRepository(session),
        action_repo=ActionRepository(session),
        graph=graph,
        redis=redis,
    )


async def test_advance_invalidates_node_tokens(
    redis_client, db_session, sample_node_and_user
) -> None:
    """advance 后 jti key + node SET 都应当被清掉。"""
    node = sample_node_and_user["node"]
    flow = sample_node_and_user["flow"]

    jtis = [uuid.uuid4().hex for _ in range(3)]
    for j in jtis:
        await _seed_token_and_register(redis_client, node.id, j)

    # seed 验证
    for j in jtis:
        assert (await redis_client.exists(f"jti:{j}")) == 1

    service = _make_service(db_session, redis_client)
    await service.submit_action(
        flow_id=flow.id,
        node_id=node.id,
        action="advance",
        result_text="同意",
        actor="li.si",
    )

    # 全部 token 失效
    for j in jtis:
        assert (await redis_client.exists(f"jti:{j}")) == 0, f"jti {j} 未被清"
    assert (await redis_client.exists(f"node:jti:{node.id}")) == 0


async def test_reject_invalidates_node_tokens(
    redis_client, db_session, sample_node_and_user
) -> None:
    """reject 同样清掉 token。"""
    node = sample_node_and_user["node"]
    flow = sample_node_and_user["flow"]
    jti = uuid.uuid4().hex
    await _seed_token_and_register(redis_client, node.id, jti)

    service = _make_service(db_session, redis_client)
    await service.submit_action(
        flow_id=flow.id,
        node_id=node.id,
        action="reject",
        result_text="不同意",
        actor="li.si",
    )
    assert (await redis_client.exists(f"jti:{jti}")) == 0


async def test_invalidate_hook_failure_does_not_block_main_flow(
    redis_client, db_session, sample_node_and_user, monkeypatch
) -> None:
    """invalidate 抛异常时主流程仍 commit + graph.ainvoke 正常返回。"""
    node = sample_node_and_user["node"]
    flow = sample_node_and_user["flow"]

    async def boom(*a, **kw):  # noqa: ANN
        raise RuntimeError("redis down")

    monkeypatch.setattr(jti_service, "invalidate_node_tokens", boom)

    service = _make_service(db_session, redis_client)
    # 不应当抛 — 仅 log warning
    result = await service.submit_action(
        flow_id=flow.id,
        node_id=node.id,
        action="advance",
        result_text="同意",
        actor="li.si",
    )
    assert result["new_status"] == "done"
