"""FastAPI 应用入口。

lifespan 顺序（启动）：
  configure_logging → get_settings() → init_db → build_graph → make_checkpointer
lifespan 顺序（关闭）：
  dispose_graph → dispose_checkpointer → dispose_engine

注意：Phase 1 容错 — DB 不通也能启动（health 会显示 fail），方便开发期。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from offboarding_flow.api.errors import register_exception_handlers
from offboarding_flow.api.health import router as health_router
from offboarding_flow.config import get_settings
from offboarding_flow.utils.logger import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动 / 关闭顺序管理。"""
    settings = get_settings()
    configure_logging(level=settings.log_level, app_mode=settings.app_mode)

    logger.info(
        "[lifespan] starting — version=%s mode=%s",
        settings.app_version,
        settings.app_mode,
    )

    # 启动顺序：DB → graph → checkpointer
    # 注意：Phase 1 容错 — DB 不通也能启动（health 会显示 fail），方便开发期
    try:
        from offboarding_flow.state_store.session import init_db

        await init_db()
        logger.info("[lifespan] DB connection OK")
    except Exception as e:
        logger.warning(
            "[lifespan] DB init failed (will continue, /api/health will report): %s",
            e,
        )

    try:
        from offboarding_flow.flow_engine.graph import build_graph

        await build_graph(use_memory_saver=False)
        logger.info("[lifespan] graph built with AsyncPostgresSaver")
    except Exception as e:
        logger.warning("[lifespan] graph build failed (will continue): %s", e)

    yield

    # 关闭
    logger.info("[lifespan] shutdown")
    try:
        from offboarding_flow.flow_engine.checkpointer import dispose_checkpointer
        from offboarding_flow.flow_engine.graph import dispose_graph
        from offboarding_flow.state_store.session import dispose_engine

        await dispose_graph()
        await dispose_checkpointer()
        await dispose_engine()
    except Exception as e:
        logger.warning("[lifespan] shutdown error: %s", e)

    # Phase 3 — 关 Redis 连接池
    try:
        from offboarding_flow.auth.redis_client import dispose_redis

        await dispose_redis()
    except Exception as e:
        logger.warning("[lifespan] dispose_redis error: %s", e)


def create_app() -> FastAPI:
    """构建 FastAPI 应用。"""
    settings = get_settings()
    app = FastAPI(
        title="offboarding-flow",
        version=settings.app_version,
        description="AI 驱动的离职流程执行系统（Phase 1: LangGraph 骨架）",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.include_router(health_router)

    # Plan 06 注册业务路由（flows + nodes）— 如果模块不存在则跳过
    try:
        from offboarding_flow.api.flows import router as flows_router
        from offboarding_flow.api.nodes import router as nodes_router

        app.include_router(flows_router)
        app.include_router(nodes_router)
        logger.info("[create_app] mounted flows_router + nodes_router")
    except ImportError as e:
        logger.info(
            "[create_app] flows/nodes routers not yet implemented (Plan 06): %s",
            e,
        )

    # Phase 3 — 鉴权路由（/api/auth/exchange + /api/auth/logout）
    try:
        from offboarding_flow.api.auth import router as auth_router

        app.include_router(auth_router)
        logger.info("[create_app] mounted auth_router")
    except ImportError as e:
        logger.info("[create_app] auth router not yet implemented: %s", e)

    # Phase 4 Slice 4B — Mattermost Outgoing Webhook（@offboarding-bot 命令入站）
    try:
        from offboarding_flow.api.mattermost_webhook import (
            router as mattermost_webhook_router,
        )

        app.include_router(mattermost_webhook_router)
        logger.info("[create_app] mounted mattermost_webhook_router")
    except ImportError as e:
        logger.info("[create_app] mattermost_webhook router not yet implemented: %s", e)

    return app


# uvicorn 入口
app = create_app()
