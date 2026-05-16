"""GET /api/health — 组件状态检查。

Phase 1 检查：db / redis / graph singleton 是否就绪。
状态分级：
- "ok": 所有组件正常
- "degraded": 关键组件失败但 API 仍能响应
始终返回 200（让 docker healthcheck 始终成功，组件状态前端自己看）。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from offboarding_flow.config import get_settings
from offboarding_flow.state_store.session import get_engine

from .envelope import ok

router = APIRouter(prefix="/api", tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check() -> dict[str, Any]:
    settings = get_settings()
    components: dict[str, str] = {}

    # DB 检查
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        components["db"] = "ok"
    except Exception as e:
        components["db"] = f"fail: {type(e).__name__}"
        logger.warning("[health] db check failed: %s", e)

    # Graph 检查（仅校验单例是否已 build）
    try:
        from offboarding_flow.flow_engine import graph as graph_mod

        components["graph"] = "ok" if graph_mod._graph is not None else "not_built"
    except Exception as e:
        components["graph"] = f"fail: {type(e).__name__}"

    # Redis 检查（Phase 1 不接 Redis 业务，仅占位；Phase 3 引入 Redis 客户端再 ping）
    components["redis"] = "not_checked"

    status = "ok" if components.get("db") == "ok" else "degraded"

    return ok(
        {
            "status": status,
            "app_mode": settings.app_mode,
            "version": settings.app_version,
            "components": components,
        }
    )
