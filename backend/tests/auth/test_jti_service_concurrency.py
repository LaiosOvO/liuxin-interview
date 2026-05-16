"""asyncio.gather 并发 race condition 测试 — PITFALLS #6 核心保证。

验收 ROADMAP §Phase 3 Success Criteria #1（jti_service 层）：
N 并发同一 jti 仅 1 个胜出，其余全失败。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from offboarding_flow.auth.jti_service import consume_jti

pytestmark = pytest.mark.asyncio


async def test_concurrent_consume_same_jti_only_one_wins(redis_client) -> None:
    """SET NX EX 原子保证：20 并发同 jti 只 1 个 True，19 个 False。

    这是 PITFALLS #6 防御的核心保证，对应 PRD §6.2.2 步骤 2/5 必须合并的诉求。
    """
    jti = uuid.uuid4().hex
    tasks = [consume_jti(redis_client, jti, ttl_seconds=60) for _ in range(20)]
    results = await asyncio.gather(*tasks)
    winners = sum(1 for r in results if r is True)
    losers = sum(1 for r in results if r is False)
    assert winners == 1, f"应当只有 1 个胜出，实际 {winners}"
    assert losers == 19, f"应当 19 个失败，实际 {losers}"


async def test_concurrent_consume_different_jtis_all_win(redis_client) -> None:
    """20 个不同 jti 并发消费全部应 True。"""
    jtis = [uuid.uuid4().hex for _ in range(20)]
    tasks = [consume_jti(redis_client, j, ttl_seconds=60) for j in jtis]
    results = await asyncio.gather(*tasks)
    assert all(r is True for r in results), "全部不同 jti 应当都成功"
