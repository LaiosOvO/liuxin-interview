"""scripts/recover_from_db.py — 从业务表重新驱动 LangGraph state（PITFALLS #2 修复路径）。

场景：node_service.submit_action 在业务事务 commit 之后调 graph.ainvoke 失败 →
action_log.status='failed' + error_message → 流程业务侧前进但 LangGraph 卡住。

本脚本扫所有 status='failed' 的 action_log，按 (flow_id, action, result_text, actor)
重新 invoke graph，成功则 mark_success，失败则 in-memory 计数重试至上限。

用法：
    uv run python -m scripts.recover_from_db [--flow-id=UUID] [--dry-run] [--max-retries=3]

环境变量（沿用应用配置）：
    POSTGRES_DSN          业务表连接（asyncpg）
    LANGGRAPH_PG_CONNINFO LangGraph checkpoint 连接（psycopg）
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys
import uuid
from typing import Any

from langgraph.types import Command

from offboarding_flow.flow_engine.graph import build_graph, dispose_graph
from offboarding_flow.state_store.repositories import ActionRepository
from offboarding_flow.state_store.session import new_session

logger = logging.getLogger("recover_from_db")


async def recover_all(
    flow_id: uuid.UUID | None = None,
    dry_run: bool = False,
    max_retries: int = 3,
    graph: Any | None = None,
) -> dict[str, int]:
    """扫描所有 failed action_log 并尝试重新 invoke graph。

    Args:
        flow_id: 仅恢复指定 flow（None = 全部）
        dry_run: 不真正 invoke，仅打印
        max_retries: 单条 action_log 在内存计数最大重试次数
        graph: 注入 graph（测试用）；None 时 build 默认

    Returns:
        dict 统计：scanned / recovered / still_failed / skipped_max_retries
    """
    stats = {"scanned": 0, "recovered": 0, "still_failed": 0, "skipped_max_retries": 0}

    if graph is None:
        graph = await build_graph()

    # 1) 取所有 failed action_log
    async with new_session() as session:
        action_repo = ActionRepository(session)
        failed_actions = await action_repo.list_failed(limit=200, flow_id=flow_id)

    stats["scanned"] = len(failed_actions)
    logger.info(
        "[recover] scanned %d failed actions (flow_id=%s, dry_run=%s)",
        stats["scanned"],
        flow_id,
        dry_run,
    )

    # 2) in-memory retry counter（action_logs 表 Phase 1 没加 retry_count 列）
    retry_counts: dict[uuid.UUID, int] = {}

    for action in failed_actions:
        if retry_counts.get(action.id, 0) >= max_retries:
            stats["skipped_max_retries"] += 1
            logger.warning(
                "[recover] action_log=%s reached max_retries=%d — skipping",
                action.id,
                max_retries,
            )
            continue

        if dry_run:
            logger.info(
                "[recover] [dry-run] would recover action_log=%s flow=%s action=%s actor=%s",
                action.id,
                action.flow_id,
                action.action,
                action.actor,
            )
            continue

        # 实际重新 invoke graph
        try:
            config = {"configurable": {"thread_id": str(action.flow_id)}}
            await graph.ainvoke(
                Command(
                    resume={
                        "action": action.action,
                        "result_text": action.result_text or "",
                        "actor": action.actor,
                    }
                ),
                config=config,
            )
            # 成功 → mark_success
            async with new_session() as ok_session:
                ok_repo = ActionRepository(ok_session)
                await ok_repo.mark_success(action.id)
                await ok_session.commit()
            stats["recovered"] += 1
            logger.info(
                "[recover] action_log=%s flow=%s — RECOVERED",
                action.id,
                action.flow_id,
            )
        except Exception as exc:
            retry_counts[action.id] = retry_counts.get(action.id, 0) + 1
            stats["still_failed"] += 1
            logger.exception(
                "[recover] action_log=%s retry=%d still failed: %s",
                action.id,
                retry_counts[action.id],
                exc,
            )

    return stats


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="从业务表重新驱动 LangGraph state（修复双写失败的 action_log）。"
    )
    parser.add_argument(
        "--flow-id",
        type=lambda s: uuid.UUID(s),
        default=None,
        help="仅恢复指定 flow_id 的 failed actions（默认扫描全部）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印不实际 invoke graph",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="单条 action_log 最大重试次数（in-memory 计数，默认 3）",
    )
    args = parser.parse_args(argv)

    try:
        stats = asyncio.run(
            recover_all(
                flow_id=args.flow_id,
                dry_run=args.dry_run,
                max_retries=args.max_retries,
            )
        )
    finally:
        # 清理 graph 单例（防再次调用时 stale）
        with contextlib.suppress(Exception):
            asyncio.run(dispose_graph())

    print(
        "recover_from_db 完成: "
        f"扫描={stats['scanned']} "
        f"成功={stats['recovered']} "
        f"仍失败={stats['still_failed']} "
        f"跳过最大重试={stats['skipped_max_retries']}"
    )
    return 0 if stats["still_failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
