"""Pytest 全局 fixture 与配置。

约定（PITFALLS #23）：
- asyncio mode=auto + loop_scope=session（在 pyproject.toml 配置）
- 避免每个测试用例创建新 event loop 导致 SQLAlchemy async engine 共享冲突

Phase 3 新增：
- redis_client fixture（function scope，flushdb 隔离）— 连 REDIS_TEST_URL 或默认 redis://localhost:6380/1
- db_session / http_client / sample_node_and_user / two_flows_with_nodes：被 tests/auth/ 与 tests/e2e/ 共用
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """显式声明事件循环策略，避免不同平台行为差异。"""
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    """如果有 anyio 测试，固定为 asyncio。"""
    return "asyncio"


def _redis_test_url() -> str:
    """优先 REDIS_TEST_URL 环境变量；否则本地 6380 db 1（避免污染 db 0）。"""
    return os.environ.get("REDIS_TEST_URL", "redis://localhost:6380/1")


@pytest_asyncio.fixture
async def redis_client():
    """function scope — 用前 flushdb 用后断开，每个测试干净状态。

    Redis 不可达时 pytest.skip — 本机 / CI 必须启 Redis 才跑这批测试：
        docker compose -f docker-compose.dev.yml up offboarding-redis -d
    或：
        REDIS_TEST_URL=redis://other-host:6379/1 pytest
    """
    client = Redis.from_url(_redis_test_url(), decode_responses=True)
    try:
        await client.ping()
    except Exception as e:
        await client.aclose()
        pytest.skip(f"Redis 不可达（{_redis_test_url()}）: {e}；启 Redis 后重跑")
    try:
        await client.flushdb()
        yield client
    finally:
        try:
            await client.flushdb()
        finally:
            await client.aclose()


# ---------------------------------------------------------------------------
# Phase 3 共享 DB/HTTP/数据 fixture（被 tests/auth/ 与 tests/e2e/ 共用）
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """function scope DB session — DB 不可达 skip。"""
    from offboarding_flow.state_store.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        try:
            await session.execute(text("SELECT 1"))
        except Exception as e:
            pytest.skip(
                f"PostgreSQL 不可达: {e}；"
                "启 docker compose -f docker-compose.dev.yml up offboarding-postgres -d 后重跑"
            )
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def http_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """FastAPI ASGI test client（无需真起 uvicorn）。"""
    from offboarding_flow.main import create_app

    app = create_app()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


@pytest_asyncio.fixture
async def sample_node_and_user(db_session: AsyncSession):
    """造 manager 角色 user + waiting_human node — exchange/race/role tests 共用。"""
    from offboarding_flow.state_store.enums import NodeStatus, Role
    from offboarding_flow.state_store.models import FlowInstance, NodeState, User

    user = User(
        id=uuid.uuid4(),
        username=f"li.si_{uuid.uuid4().hex[:8]}",
        email="li.si@demo.local",
        display_name="李四",
        role=Role.MANAGER.value,
    )
    flow = FlowInstance(id=uuid.uuid4(), employee_id="zhang.san", status="in_progress")
    node = NodeState(
        id=uuid.uuid4(),
        flow_id=flow.id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
        assignee=user.username,
    )
    db_session.add_all([user, flow, node])
    await db_session.commit()
    try:
        yield {"flow": flow, "node": node, "user": user}
    finally:
        await db_session.delete(node)
        await db_session.delete(flow)
        await db_session.delete(user)
        await db_session.commit()


@pytest_asyncio.fixture
async def two_flows_with_nodes(db_session: AsyncSession):
    """造两个 flow 各带一个 waiting_human node + 一个 user — cross_flow 测试用。"""
    from offboarding_flow.state_store.enums import NodeStatus, Role
    from offboarding_flow.state_store.models import FlowInstance, NodeState, User

    user = User(
        id=uuid.uuid4(),
        username=f"li.si_{uuid.uuid4().hex[:8]}",
        email="li.si@demo.local",
        display_name="李四",
        role=Role.MANAGER.value,
    )
    flow_a = FlowInstance(id=uuid.uuid4(), employee_id="zhang.san", status="in_progress")
    flow_b = FlowInstance(id=uuid.uuid4(), employee_id="wang.wu", status="in_progress")
    node_a = NodeState(
        id=uuid.uuid4(),
        flow_id=flow_a.id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
        assignee=user.username,
    )
    node_b = NodeState(
        id=uuid.uuid4(),
        flow_id=flow_b.id,
        node_name="manager_review",
        node_title="上级审批",
        status=NodeStatus.WAITING_HUMAN.value,
        assignee=user.username,
    )
    db_session.add_all([user, flow_a, flow_b, node_a, node_b])
    await db_session.commit()
    try:
        yield {
            "user": user,
            "flow_a": flow_a,
            "flow_b": flow_b,
            "node_a": node_a,
            "node_b": node_b,
        }
    finally:
        for obj in [node_a, node_b, flow_a, flow_b, user]:
            await db_session.delete(obj)
        await db_session.commit()
