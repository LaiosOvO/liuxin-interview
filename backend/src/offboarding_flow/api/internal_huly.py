"""POST /api/internal/huly/event — 接收 huly-bridge sidecar 反向 webhook（HULY-07）。

设计：
- sidecar src/listener.ts 检测到 chat 消息时 POST 到本路由（X-Bridge-Token 鉴权）
- 鉴权失败 → 401 bridge_auth_failed（NFR-05）
- 鉴权成功 → 调 app.state.huly_listener.handle_webhook(payload)
- listener 未初始化（IM_PROVIDER != huly 启动场景）→ 503

注意：
- 本路由前缀 `/api/internal/huly` 内网 only — 不应通过外部网关暴露
- BRIDGE_TOKEN 与 sidecar 端共享，docker-compose env 注入
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request

from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/internal/huly", tags=["internal-huly"])


@router.post("/event")
async def huly_event(
    request: Request,
    payload: dict[str, Any],
    x_bridge_token: Annotated[str | None, Header(alias="X-Bridge-Token")] = None,
) -> dict[str, Any]:
    """接收 sidecar 反向 chat webhook。

    Args:
        payload: ChatEventPayload + channel_type（见 huly_listener.handle_webhook 文档）
        x_bridge_token: X-Bridge-Token header（与 sidecar 共享）

    Returns:
        {"ok": True} 表示已交付给 listener

    Raises:
        HTTPException(401): BRIDGE_TOKEN 缺失或不匹配
        HTTPException(503): app.state.huly_listener 未初始化（IM_PROVIDER != huly）
    """
    settings = get_settings()
    expected = settings.huly_bridge_token

    # 鉴权：expected 必须非空 + 实际 token 匹配
    if not expected:
        logger.warning("[internal_huly] HULY_BRIDGE_TOKEN 配置为空 — 拒绝所有 webhook")
        raise HTTPException(status_code=401, detail="bridge_auth_failed")
    if x_bridge_token is None or x_bridge_token != expected:
        logger.warning(
            "[internal_huly] X-Bridge-Token 不匹配（presented=%s）",
            "<missing>" if x_bridge_token is None else f"{x_bridge_token[:4]}...",
        )
        raise HTTPException(status_code=401, detail="bridge_auth_failed")

    # 取 listener 实例（main.py lifespan 注入 app.state.huly_listener）
    listener = getattr(request.app.state, "huly_listener", None)
    if listener is None:
        logger.warning("[internal_huly] huly_listener 未初始化 — 检查 IM_PROVIDER 是否为 huly")
        raise HTTPException(status_code=503, detail="huly_listener_not_initialized")

    await listener.handle_webhook(payload)
    return {"ok": True}
