"""Pytest 全局 fixture 与配置。

约定（PITFALLS #23）：
- asyncio mode=auto + loop_scope=session（在 pyproject.toml 配置）
- 避免每个测试用例创建新 event loop 导致 SQLAlchemy async engine 共享冲突

Phase 3 新增：
- redis_client fixture（function scope，flushdb 隔离）— 连 REDIS_TEST_URL 或默认 redis://localhost:6380/1
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio
from redis.asyncio import Redis


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
