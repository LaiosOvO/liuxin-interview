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

    # IM listener — 支持多 listener 并存（5.3 抽象升级）：
    #   IM_PROVIDERS=mattermost,huly  → 同时启 MM + Huly listener，双平台对 bot 说"我要离职"都能起流程
    #   IM_PROVIDERS=""  → 回退到 IM_PROVIDER (单)，保持 backwards compat
    # 用 IMListener 抽象类型注解，所有 provider 走同一套 Protocol
    from offboarding_flow.im.protocol import IMListener as _IMListenerProto

    im_listeners: list[_IMListenerProto] = []
    app.state.huly_listener = None  # Plan 05 — internal_huly 路由会读这个属性

    # 解析 provider 列表：优先 IM_PROVIDERS 复数，回退到 IM_PROVIDER 单值
    if settings.im_providers and settings.im_providers.strip():
        providers = [p.strip().lower() for p in settings.im_providers.split(",") if p.strip()]
    else:
        providers = [(settings.im_provider or "mattermost").lower()]
    logger.info("[lifespan] IM providers requested: %s", providers)

    try:
        from offboarding_flow.im.dispatcher import dispatch_message

        for provider in providers:
            try:
                listener: _IMListenerProto | None = None
                if provider == "mattermost" and settings.mattermost_bot_token:
                    from offboarding_flow.workers.mattermost_listener import MattermostListener

                    listener = MattermostListener(settings)
                    app.state.mm_listener = listener
                elif provider == "huly":
                    from offboarding_flow.workers.huly_listener import HulyListener

                    listener = HulyListener(settings)
                    app.state.huly_listener = listener
                elif provider == "lark" or provider == "feishu":
                    # 飞书 WebSocket 长连接 — 独立线程跑，不走 IMListener Protocol
                    # （bot 接收 @ 消息 → MeetingService → 飞书 Doc → 回复用户）
                    from offboarding_flow.workers.lark_listener import start_lark_listener

                    lark_inst = start_lark_listener(settings)
                    app.state.lark_listener = lark_inst
                    logger.info("[lifespan] ✓ lark listener started (WebSocket 长连接, 独立线程)")
                    continue  # 不走 IMListener Protocol register / start
                else:
                    logger.info(
                        "[lifespan] skip provider=%s (mattermost 需 bot_token / huly 走 webhook / lark 走 WebSocket)",
                        provider,
                    )
                    continue

                assert isinstance(listener, _IMListenerProto)
                listener.register_command_listener(dispatch_message)
                await listener.start()
                im_listeners.append(listener)
                logger.info(
                    "[lifespan] ✓ %s listener started (dispatch=im.dispatcher.dispatch_message)",
                    getattr(listener, "name", provider),
                )
            except Exception as inner:
                logger.warning(
                    "[lifespan] IM listener[%s] start failed (will continue 其他 listener): %s",
                    provider,
                    inner,
                )
    except Exception as e:
        logger.warning("[lifespan] IM listener loop fatal (continue without IM): %s", e)

    app.state.im_listeners = im_listeners  # 暴露给运维 / healthcheck 用

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

    # 停所有 IM listener（mattermost / huly / ... 任意组合）
    for listener in im_listeners:
        try:
            await listener.stop()
            logger.info(
                "[lifespan] ✓ %s listener stopped",
                getattr(listener, "name", "unknown"),
            )
        except Exception as e:
            logger.warning(
                "[lifespan] %s listener stop error: %s",
                getattr(listener, "name", "unknown"),
                e,
            )

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

    # Phase 8 B-full — 去 sidecar 后 internal_huly 路由已删（无 sidecar 反向推送）

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
