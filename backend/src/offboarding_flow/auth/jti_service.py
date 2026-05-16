"""jti 一次性消费 + 节点 token 批量失效。

核心（CONTEXT §D5 + PITFALLS #6）：
- consume_jti 用 Redis SET key value NX EX 原子操作 — 防双击 race condition
- register_node_token 把 jti 加入 node:jti:{node_id} SET（pipeline 防 SET 永驻）
- invalidate_node_tokens 节点状态变更时清掉该 node 所有未消费 token
"""

from __future__ import annotations

import logging
from uuid import UUID

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _jti_key(jti: str) -> str:
    return f"jti:{jti}"


def _node_set_key(node_id: str | UUID) -> str:
    return f"node:jti:{node_id}"


async def consume_jti(redis: Redis, jti: str, *, ttl_seconds: int) -> bool:
    """SET NX EX 原子消费 — PITFALLS #6 防双击 race condition。

    Returns:
        True — 首次消费（token 有效）
        False — 已被消费（重放 / 双击 race 失败）
    """
    # redis-py 5.x: set(..., nx=True) 返回 True（成功）或 None（key 已存在）
    result = await redis.set(_jti_key(jti), "1", nx=True, ex=ttl_seconds)
    return result is True or result == "OK"


async def is_jti_consumed(redis: Redis, jti: str) -> bool:
    """仅检查不消费 — 用于 debug / 测试。"""
    # redis-py 6.x overload 返回 Awaitable[int] | int — async client 实际是 Awaitable
    exists = await redis.exists(_jti_key(jti))  # type: ignore[misc]
    return int(exists) > 0


async def register_node_token(
    redis: Redis,
    node_id: str | UUID,
    jti: str,
    *,
    ttl_seconds: int,
) -> None:
    """把 jti 注册到 node SET — 节点状态变更时方便批量失效。

    用 pipeline 防止 SET 加成员后忘记 EXPIRE（永驻泄漏）。
    """
    key = _node_set_key(node_id)
    async with redis.pipeline(transaction=False) as pipe:
        # redis-py 6.x async pipeline 方法返回 self（同 sync 行为）；mypy 上游类型不准
        pipe.sadd(key, jti)  # type: ignore[misc]
        pipe.expire(key, ttl_seconds)  # type: ignore[misc]
        await pipe.execute()


async def invalidate_node_tokens(
    redis: Redis,
    node_id: str | UUID,
) -> int:
    """节点状态变更时批量失效该节点所有未消费 token。

    Returns:
        删除的 jti 数量
    """
    set_key = _node_set_key(node_id)
    # redis-py 6.x overload union — async client 实际是 Awaitable
    jtis = await redis.smembers(set_key)  # type: ignore[misc]
    if not jtis:
        return 0
    keys_to_delete = [_jti_key(j) for j in jtis] + [set_key]
    await redis.delete(*keys_to_delete)
    logger.info(
        "[jti_service] invalidated %d tokens for node=%s",
        len(jtis),
        node_id,
    )
    return len(jtis)
