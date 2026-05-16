#!/usr/bin/env python3
"""清理 LangGraph checkpoint 表 — 防表无限增长（PITFALLS #25）。

策略：
- 删除 > N 天的 langgraph.checkpoints / checkpoint_blobs / checkpoint_writes
- 默认 30 天，可通过 CLI `--days N` 调整
- 演示环境定期跑（建议 cron 每周一次）

用法：
    # dry-run（查看待删除行数，不实际删）
    python scripts/cleanup_old_checkpoints.py --dry-run

    # 实际执行（删除 > 30 天的 checkpoint）
    python scripts/cleanup_old_checkpoints.py

    # 自定义保留窗口（删 > 7 天）
    python scripts/cleanup_old_checkpoints.py --days 7

依赖：
    - 后端 .env 已配置 LANGGRAPH_PG_CONNINFO
    - psycopg 已安装（与 backend 共用）

注意：
    - 业务表（app.flow_instances 等）由 alembic 管，不在本脚本范围
    - checkpoint 删除后流程实例仍存（业务表 = source of truth）
    - 已归档的流程（status='completed' / 'rejected'）可放心清理
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# 让脚本能 import backend 包
_BACKEND_SRC = Path(__file__).parent.parent / "backend" / "src"
if _BACKEND_SRC.exists():
    sys.path.insert(0, str(_BACKEND_SRC))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-5s %(name)s — %(message)s",
)
logger = logging.getLogger("cleanup_old_checkpoints")


def _get_dsn() -> str:
    """优先 env LANGGRAPH_PG_CONNINFO；fallback 用 backend Settings。"""
    env_dsn = os.environ.get("LANGGRAPH_PG_CONNINFO")
    if env_dsn:
        return env_dsn
    try:
        from offboarding_flow.config import get_settings

        return get_settings().langgraph_pg_conninfo
    except Exception as e:
        logger.error("无法从 backend Settings 读 DSN：%s", e)
        logger.error("请显式设置 LANGGRAPH_PG_CONNINFO 环境变量")
        sys.exit(2)


def cleanup(dsn: str, days: int, dry_run: bool) -> dict[str, int]:
    """清理 langgraph schema 中过期的 checkpoint。

    Args:
        dsn: postgres conninfo (psycopg3 sync)
        days: 保留天数（删除 created_at < now() - days）
        dry_run: True = 仅 count 不删

    Returns:
        {表名: 行数} 字典
    """
    try:
        import psycopg
    except ImportError:
        logger.error("psycopg 未安装；请在 backend 环境跑：uv run python scripts/cleanup_old_checkpoints.py")
        sys.exit(3)

    cutoff = datetime.now(UTC) - timedelta(days=days)
    logger.info(
        "[cleanup] cutoff=%s (保留 %d 天内的 checkpoint, dry_run=%s)",
        cutoff.isoformat(),
        days,
        dry_run,
    )

    # langgraph 0.2+ checkpoint 表结构：
    #   - checkpoints       (主表，含 created_at)
    #   - checkpoint_blobs  (字段 payload)
    #   - checkpoint_writes (字段 task_id)
    # 旧版可能没有 created_at 列；先 introspect 再决策
    counts: dict[str, int] = {}

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # 1. 探测表是否存在
            cur.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'langgraph'
                  AND table_name IN ('checkpoints', 'checkpoint_blobs', 'checkpoint_writes')
                """
            )
            existing = {row[0] for row in cur.fetchall()}
            logger.info("[cleanup] langgraph schema 表: %s", existing)

            if not existing:
                logger.warning(
                    "[cleanup] langgraph schema 无 checkpoint 表 — 是否已 setup？"
                )
                return counts

            # 2. 按 thread_id 找出过期的 checkpoint（thread_id = flow_id）
            #    思路：通过业务表 app.flow_instances 查 completed / archived
            #    早于 cutoff 的 flow_id，删对应 langgraph.checkpoints 行
            cur.execute(
                """
                SELECT id::text
                FROM app.flow_instances
                WHERE status IN ('completed', 'rejected')
                  AND updated_at < %s
                """,
                (cutoff,),
            )
            stale_flow_ids = [row[0] for row in cur.fetchall()]
            logger.info(
                "[cleanup] 找到 %d 个已归档且 updated_at < cutoff 的流程",
                len(stale_flow_ids),
            )

            if not stale_flow_ids:
                logger.info("[cleanup] 无可清理的 checkpoint")
                return counts

            # 3. 删 checkpoint（thread_id = flow_id 字符串）
            for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                if table not in existing:
                    continue
                # checkpoints 表的 thread_id 列就是 LangGraph 的 thread_id
                count_sql = (
                    f"SELECT COUNT(*) FROM langgraph.{table} "
                    "WHERE thread_id = ANY(%s)"
                )
                cur.execute(count_sql, (stale_flow_ids,))
                count = cur.fetchone()[0]
                counts[table] = count

                if dry_run:
                    logger.info("[dry-run] 将删除 langgraph.%s = %d 行", table, count)
                else:
                    del_sql = (
                        f"DELETE FROM langgraph.{table} WHERE thread_id = ANY(%s)"
                    )
                    cur.execute(del_sql, (stale_flow_ids,))
                    logger.info("[cleanup] 已删除 langgraph.%s = %d 行", table, count)

            if not dry_run:
                conn.commit()
                logger.info("[cleanup] commit 成功")
            else:
                conn.rollback()

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理 LangGraph checkpoint 表（PITFALLS #25）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="保留天数（默认 30；删除已归档且 > N 天的 checkpoint）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅 count 不删",
    )
    parser.add_argument(
        "--dsn",
        type=str,
        default=None,
        help="可选：覆盖 LANGGRAPH_PG_CONNINFO env",
    )
    args = parser.parse_args()

    dsn = args.dsn or _get_dsn()
    safe_dsn = dsn.split("@", 1)[-1] if "@" in dsn else dsn
    logger.info("[cleanup] 目标 DSN: ***@%s", safe_dsn)

    counts = cleanup(dsn, args.days, args.dry_run)
    logger.info("[cleanup] 完成 — 清理统计: %s", counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
