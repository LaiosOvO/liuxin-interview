"""jti_service 集成测试 — 真 Redis（不 mock — CLAUDE.md §2.3）。

约定：
- REDIS_TEST_URL=redis://localhost:6380/1 或 CI 注入
- 本地启 Redis：`docker compose -f docker-compose.dev.yml up offboarding-redis -d`
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from offboarding_flow.auth.jti_service import (
    consume_jti,
    invalidate_node_tokens,
    is_jti_consumed,
    register_node_token,
)

pytestmark = pytest.mark.asyncio


async def test_consume_jti_first_time_returns_true(redis_client) -> None:
    """首次消费返回 True。"""
    jti = uuid.uuid4().hex
    ok = await consume_jti(redis_client, jti, ttl_seconds=60)
    assert ok is True


async def test_consume_jti_replay_returns_false(redis_client) -> None:
    """同一 jti 第二次消费返回 False（重放攻击 / 双击）。"""
    jti = uuid.uuid4().hex
    first = await consume_jti(redis_client, jti, ttl_seconds=60)
    second = await consume_jti(redis_client, jti, ttl_seconds=60)
    assert first is True
    assert second is False


async def test_is_jti_consumed_reports_state(redis_client) -> None:
    """is_jti_consumed 仅检查不消费，状态反映正确。"""
    jti = uuid.uuid4().hex
    assert (await is_jti_consumed(redis_client, jti)) is False
    await consume_jti(redis_client, jti, ttl_seconds=60)
    assert (await is_jti_consumed(redis_client, jti)) is True


async def test_different_jti_independent(redis_client) -> None:
    """两个不同 jti 互不干扰。"""
    a = uuid.uuid4().hex
    b = uuid.uuid4().hex
    await consume_jti(redis_client, a, ttl_seconds=60)
    result_b = await consume_jti(redis_client, b, ttl_seconds=60)
    assert result_b is True


async def test_consume_jti_ttl_applied(redis_client) -> None:
    """TTL 到期后再消费同 jti 应当 True（key 已自然过期）。"""
    jti = uuid.uuid4().hex
    await consume_jti(redis_client, jti, ttl_seconds=2)
    await asyncio.sleep(2.5)
    ok = await consume_jti(redis_client, jti, ttl_seconds=60)
    assert ok is True


async def test_register_node_token_adds_to_set(redis_client) -> None:
    """register_node_token 把 jti 加进 node:jti:{id} SET。"""
    node_id = uuid.uuid4()
    jti = uuid.uuid4().hex
    await register_node_token(redis_client, node_id, jti, ttl_seconds=60)
    members = await redis_client.smembers(f"node:jti:{node_id}")
    assert jti in members


async def test_register_node_token_sets_ttl(redis_client) -> None:
    """node:jti:{id} SET 应当带 TTL，防永驻泄漏。"""
    node_id = uuid.uuid4()
    jti = uuid.uuid4().hex
    await register_node_token(redis_client, node_id, jti, ttl_seconds=60)
    ttl = await redis_client.ttl(f"node:jti:{node_id}")
    assert 0 < ttl <= 60


async def test_invalidate_node_tokens_clears_all(redis_client) -> None:
    """invalidate 清掉 SET + 所有 jti:{value} key。"""
    node_id = uuid.uuid4()
    jtis = [uuid.uuid4().hex for _ in range(3)]
    for j in jtis:
        await consume_jti(redis_client, j, ttl_seconds=60)
        await register_node_token(redis_client, node_id, j, ttl_seconds=60)

    # seed 校验
    for j in jtis:
        assert (await redis_client.exists(f"jti:{j}")) == 1

    deleted = await invalidate_node_tokens(redis_client, node_id)
    assert deleted == 3

    # node SET 应当被清
    assert (await redis_client.exists(f"node:jti:{node_id}")) == 0
    # 全部 jti key 删除
    for j in jtis:
        assert (await redis_client.exists(f"jti:{j}")) == 0
    # 失效后再消费同 jti 全部 True（key 已不存在）
    for j in jtis:
        ok = await consume_jti(redis_client, j, ttl_seconds=60)
        assert ok is True


async def test_invalidate_node_tokens_empty_set_returns_zero(redis_client) -> None:
    """空 node SET 返回 0。"""
    node_id = uuid.uuid4()
    deleted = await invalidate_node_tokens(redis_client, node_id)
    assert deleted == 0


async def test_invalidate_isolates_to_node(redis_client) -> None:
    """invalidate node_a 不影响 node_b 的 token。"""
    node_a = uuid.uuid4()
    node_b = uuid.uuid4()
    jti_a = uuid.uuid4().hex
    jti_b = uuid.uuid4().hex
    await consume_jti(redis_client, jti_a, ttl_seconds=60)
    await register_node_token(redis_client, node_a, jti_a, ttl_seconds=60)
    await consume_jti(redis_client, jti_b, ttl_seconds=60)
    await register_node_token(redis_client, node_b, jti_b, ttl_seconds=60)

    await invalidate_node_tokens(redis_client, node_a)

    # node_b 的 jti 不受影响
    assert (await redis_client.exists(f"jti:{jti_b}")) == 1
    assert (await redis_client.exists(f"node:jti:{node_b}")) == 1
