"""FastAPI 依赖注入容器。

提供 session / Repository / Service / graph 的 DI。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.auth.deps import get_redis_dep
from offboarding_flow.flow_engine.graph import get_graph
from offboarding_flow.services import FlowService, NodeService
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
)
from offboarding_flow.state_store.session import get_sessionmaker, new_session


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """每个请求一个 session（autoflush 关，手动 commit 在 service 层）。"""
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_flow_repo(session: SessionDep) -> FlowRepository:
    return FlowRepository(session)


def get_node_repo(session: SessionDep) -> NodeRepository:
    return NodeRepository(session)


def get_action_repo(session: SessionDep) -> ActionRepository:
    return ActionRepository(session)


def get_flow_service(
    session: SessionDep,
    flow_repo: Annotated[FlowRepository, Depends(get_flow_repo)],
    node_repo: Annotated[NodeRepository, Depends(get_node_repo)],
    action_repo: Annotated[ActionRepository, Depends(get_action_repo)],
) -> FlowService:
    graph = get_graph()
    return FlowService(session, flow_repo, node_repo, action_repo, graph)


def get_node_service(
    session: SessionDep,
    flow_repo: Annotated[FlowRepository, Depends(get_flow_repo)],
    node_repo: Annotated[NodeRepository, Depends(get_node_repo)],
    action_repo: Annotated[ActionRepository, Depends(get_action_repo)],
    redis: Annotated[Redis, Depends(get_redis_dep)],
) -> NodeService:
    """合并 Phase 2 (session_factory 失败补偿) + Phase 3 (Redis token 失效)。"""
    graph = get_graph()
    return NodeService(
        session=session,
        flow_repo=flow_repo,
        node_repo=node_repo,
        action_repo=action_repo,
        graph=graph,
        session_factory=new_session,
        redis=redis,
    )
