"""异步 DB session 工厂 + engine 单例。

约定（CONTEXT §2）：
- DSN 用 asyncpg（postgresql+asyncpg://）
- 通过 connect_args server_settings 锁 search_path 到 app（业务连接）
- expire_on_commit=False（FastAPI Depends 模式下减少不必要的 expire）
- pool_size=5, max_overflow=15（演示环境足够）
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回（或创建）全局 async engine 单例。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.postgres_dsn,
            pool_size=5,
            max_overflow=15,
            pool_pre_ping=True,
            connect_args={
                "server_settings": {"search_path": "app,public"},
            },
        )
        logger.info("[session] engine created (pool 5+15)")
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """返回 sessionmaker 单例。"""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 入口：每请求一个 session。"""
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


@asynccontextmanager
async def new_session() -> AsyncIterator[AsyncSession]:
    """打开一个独立的 AsyncSession（用于双写规范 failure path 补偿写入）。

    Phase 2 Plan 01：node_service.submit_action 在原 session commit 之后，
    若 graph.ainvoke 抛异常，需用新 session 写 action_log.failed —
    原 session 已被 ASGI 请求生命周期托管，不能复用。
    """
    sm = get_sessionmaker()
    async with sm() as session:
        yield session


async def init_db() -> None:
    """启动时调用：确认 engine 可连。"""
    engine = get_engine()
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    logger.info("[session] init_db OK — DB reachable")


async def dispose_engine() -> None:
    """关闭 engine + 清单例（FastAPI shutdown）。"""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None
        logger.info("[session] engine disposed")
