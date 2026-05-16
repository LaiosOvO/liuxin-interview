"""Redis async client 单例 — Phase 3 jti 黑名单 + Phase 4 outbox 用。

约定（CONTEXT §D5 + Plan 02）：
- 全局单例 _redis，FastAPI lifespan 不显式 init（懒加载首次 get_redis）
- decode_responses=True 让所有 GET 返回 str 而非 bytes（简化 jti 比较）
- dispose_redis 在 lifespan shutdown 调，关连接池
"""

from __future__ import annotations

import logging

from redis.asyncio import ConnectionPool, Redis

from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)

_redis: Redis | None = None
_pool: ConnectionPool | None = None


async def get_redis() -> Redis:
    """获取 Redis 单例（懒加载）。"""
    global _redis, _pool
    if _redis is None:
        settings = get_settings()
        _pool = ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=10,
        )
        _redis = Redis(connection_pool=_pool)
        logger.info("[redis_client] initialized: %s", settings.redis_url)
    return _redis


async def dispose_redis() -> None:
    """lifespan shutdown 调用 — 关闭连接池。"""
    global _redis, _pool
    if _redis is not None:
        await _redis.aclose()  # type: ignore[attr-defined]
        _redis = None
    if _pool is not None:
        await _pool.aclose()  # type: ignore[attr-defined]
        _pool = None
    logger.info("[redis_client] disposed")
