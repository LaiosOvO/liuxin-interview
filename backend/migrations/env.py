"""Alembic env — 异步 + 过滤 langgraph schema + 用 Settings 读取 DSN。

关键约定（CONTEXT §2 + PITFALLS #1）：
- include_object 过滤 schema == 'langgraph'（防 autogenerate 误删 LangGraph 表）
- version_table_schema = 'app'（alembic_version 表也放 app schema）
- include_schemas=True 让 alembic 知道我们用 schema（默认只看 public）
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from offboarding_flow.config import get_settings
from offboarding_flow.state_store.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to):
    """关键：过滤 langgraph schema 的所有对象（PITFALLS #1）。

    alembic autogenerate 会扫到 LangGraph 的 checkpoints 等表，如果不过滤
    会被误删（因为我们的 metadata 不知道这些表）。
    """
    if type_ == "table":
        schema = getattr(object, "schema", None)
        if schema == "langgraph":
            return False
        if schema and schema.startswith("langgraph"):
            return False
    return True


def run_migrations_offline() -> None:
    """offline 模式 — 不需要 DB 连接，输出 SQL 到 stdout。"""
    settings = get_settings()
    url = settings.postgres_dsn_sync
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
        include_schemas=True,
        version_table_schema="app",
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table_schema="app",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    settings = get_settings()
    configuration = config.get_section(config.config_ini_section, {}) or {}
    configuration["sqlalchemy.url"] = settings.postgres_dsn
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
