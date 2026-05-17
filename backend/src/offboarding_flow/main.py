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

    # Phase 4 Slice 4D — 起 OutboxDrainWorker（事件驱动 in-process asyncio.Event + 60s 心跳）
    outbox_worker = None
    outbox_task = None
    try:
        import asyncio

        from offboarding_flow.workers import OutboxDrainWorker

        outbox_worker = OutboxDrainWorker(settings)
        outbox_task = asyncio.create_task(outbox_worker.run())
        app.state.outbox_worker = outbox_worker
        app.state.outbox_task = outbox_task
        logger.info("[lifespan] outbox drain worker started (event-driven)")
    except Exception as e:
        logger.warning("[lifespan] outbox worker start failed (will continue): %s", e)

    # IM listener — 按 IM_PROVIDER 动态选择实现（ABS-01 / ABS-04 / HULY-07）
    # 让 bot 在线 + 支持 DM（用户要求）
    # 用 IMListener 抽象类型注解，让 MattermostListener / HulyListener 双绑兼容
    from offboarding_flow.im.protocol import IMListener as _IMListenerProto

    im_listener: _IMListenerProto | None = None
    app.state.huly_listener = None  # Plan 05 — internal_huly 路由会读这个属性
    try:
        from offboarding_flow.im.dispatcher import dispatch_message

        provider = (settings.im_provider or "mattermost").lower()
        if provider == "mattermost" and settings.mattermost_bot_token:
            from offboarding_flow.workers.mattermost_listener import MattermostListener

            im_listener = MattermostListener(settings)
            app.state.mm_listener = im_listener
            logger.info("[lifespan] selected IM listener: mattermost")
        elif provider == "huly":
            from offboarding_flow.workers.huly_listener import HulyListener

            im_listener = HulyListener(settings)
            app.state.huly_listener = im_listener
            logger.info("[lifespan] selected IM listener: huly (webhook 模式)")
        else:
            logger.info(
                "[lifespan] no IM listener — provider=%s（mattermost 需 bot_token，huly 走 webhook）",
                provider,
            )

        if im_listener is not None:
            assert isinstance(im_listener, _IMListenerProto)  # runtime_checkable Protocol 校验
            im_listener.register_command_listener(dispatch_message)
            await im_listener.start()
            logger.info(
                "[lifespan] %s listener started (dispatch=im.dispatcher.dispatch_message)",
                getattr(im_listener, "name", "unknown"),
            )
    except Exception as e:
        logger.warning("[lifespan] IM listener start failed (will continue): %s", e)
        im_listener = None

    # 兼容老代码 — app.state.mm_listener 别名（其它地方可能引用）
    # im_listener 是 mattermost 时已在上面写入 app.state.mm_listener，本处不重复

    # Phase 6 — 起 TimeoutScanWorker（NOTI-05 + TIMEOUT-01，每 60s 扫超时节点）
    timeout_worker = None
    timeout_task = None
    try:
        import asyncio

        from offboarding_flow.workers import TimeoutScanWorker

        timeout_worker = TimeoutScanWorker(settings)
        timeout_task = asyncio.create_task(timeout_worker.run())
        app.state.timeout_worker = timeout_worker
        app.state.timeout_task = timeout_task
        logger.info(
            "[lifespan] timeout scan worker started (SLA=%.2fh interval=%.0fs)",
            settings.node_timeout_hours
            if settings.demo_timeout_override_hours is None
            else settings.demo_timeout_override_hours,
            settings.timeout_scan_interval_seconds,
        )
    except Exception as e:
        logger.warning("[lifespan] timeout scan worker start failed (will continue): %s", e)

    yield

    # 停 IM listener（mattermost 或 huly）
    if im_listener is not None:
        try:
            await im_listener.stop()
        except Exception as e:
            logger.warning("[lifespan] im_listener stop error: %s", e)

    # Phase 6 — 优雅停止 timeout worker（先于 outbox，让最后一批 outbox 仍能 drain）
    if timeout_worker is not None and timeout_task is not None:
        try:
            await timeout_worker.stop()
            await asyncio.wait_for(timeout_task, timeout=5.0)
            logger.info("[lifespan] timeout scan worker stopped")
        except Exception as e:
            logger.warning("[lifespan] timeout worker stop error: %s", e)

    # Phase 4 Slice 4D — 优雅停止 outbox worker
    if outbox_worker is not None and outbox_task is not None:
        try:
            await outbox_worker.stop()
            await asyncio.wait_for(outbox_task, timeout=5.0)
            logger.info("[lifespan] outbox drain worker stopped")
        except Exception as e:
            logger.warning("[lifespan] outbox worker stop error: %s", e)

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

    # Phase 8 / HULY-07 — sidecar 反向 webhook 入口（BRIDGE_TOKEN 鉴权）
    try:
        from offboarding_flow.api.internal_huly import router as internal_huly_router

        app.include_router(internal_huly_router)
        logger.info("[create_app] mounted internal_huly_router (Plan 08-05)")
    except ImportError as e:
        logger.info("[create_app] internal_huly router not yet implemented: %s", e)

    # Phase 8 / Plan 07 — MCP HTTP /mcp/* mount（MCP-05，settings.mcp_http_mounted=True 时）
    # 避免起独立容器；演示部署 / 远程 LLM 客户端走这条
    # Bearer JWT 鉴权由 MagicLinkAuthMiddleware 处理（C-2 复用 magic-link JWT）
    if settings.mcp_http_mounted:
        try:
            from offboarding_flow.mcp.server import mcp

            # FastMCP 3.x http_app() 返回 starlette 兼容 ASGI sub-app
            app.mount("/mcp", mcp.http_app())
            logger.info("[create_app] mounted FastMCP HTTP /mcp/* (MCP-05)")
        except ImportError as e:
            logger.info("[create_app] MCP server not available: %s", e)
    else:
        logger.info(
            "[create_app] MCP_HTTP_MOUNTED=false — MCP 走 stdio mode "
            "(python -m offboarding_flow.mcp.runner stdio)"
        )

    return app


# uvicorn 入口
app = create_app()
