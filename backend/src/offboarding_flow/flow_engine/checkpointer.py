"""LangGraph AsyncPostgresSaver 工厂 + CLI setup 入口（CONTEXT §2 + §4）。

关键约定（PITFALLS #1）：
- psycopg 3 必须 autocommit=True + row_factory=dict_row + prepare_threshold=0
- 否则 langgraph-checkpoint-postgres 在某些场景 deadlock

双 schema（CONTEXT §2）：
- LangGraph 表由 saver.setup() 自管（默认 schema 'public'，但我们在 init-db.sql 创建了
  langgraph schema 备用；本 Phase 1 用默认即可，schema 隔离的关键是 alembic 不扫这些表 — env.py 已 include_object 过滤）
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None


async def make_checkpointer(conninfo: str | None = None) -> AsyncPostgresSaver:
    """创建（或返回已有）AsyncPostgresSaver 单例。

    用 AsyncConnectionPool + psycopg 3 配置 PITFALLS #1 推荐参数。
    """
    global _saver, _pool
    if _saver is not None:
        return _saver

    if conninfo is None:
        settings = get_settings()
        conninfo = settings.langgraph_pg_conninfo

    _pool = AsyncConnectionPool(
        conninfo=conninfo,
        max_size=10,
        min_size=2,
        kwargs={
            "autocommit": True,
            "row_factory": dict_row,
            "prepare_threshold": 0,
        },
        open=False,
    )
    await _pool.open()
    _saver = AsyncPostgresSaver(_pool)
    logger.info("[checkpointer] AsyncPostgresSaver created (pool 2-10)")
    return _saver


async def setup_checkpointer_schema() -> None:
    """显式跑 saver.setup() — 创建 LangGraph 所需表（幂等）。

    entrypoint.sh 在启动 uvicorn 前调用本方法。
    """
    saver = await make_checkpointer()
    logger.info("[checkpointer] setup() — creating LangGraph schema tables")
    await saver.setup()
    logger.info("[checkpointer] setup() complete")


async def dispose_checkpointer() -> None:
    """关闭 pool — 用于 FastAPI shutdown。"""
    global _saver, _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        _saver = None
        logger.info("[checkpointer] pool disposed")


def _run_setup_cli() -> None:
    """CLI 入口：`python -m offboarding_flow.flow_engine.checkpointer --setup`."""
    parser = argparse.ArgumentParser(description="LangGraph checkpointer setup")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="跑 saver.setup() 创建 LangGraph schema 表（幂等）",
    )
    args = parser.parse_args()

    if args.setup:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        )
        asyncio.run(_setup_then_dispose())
    else:
        parser.print_help()


async def _setup_then_dispose() -> None:
    try:
        await setup_checkpointer_schema()
    finally:
        await dispose_checkpointer()


if __name__ == "__main__":
    _run_setup_cli()
