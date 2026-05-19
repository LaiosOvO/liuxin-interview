"""POST /api/flows/{flow_id}/nodes/{node_id}/actions 路由。"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from offboarding_flow.api.deps import get_node_service
from offboarding_flow.api.envelope import ok
from offboarding_flow.auth import jwt_service
from offboarding_flow.auth.schemas import SessionPayload
from offboarding_flow.config import get_settings
from offboarding_flow.services import NodeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/flows", tags=["nodes"])


class SubmitActionRequest(BaseModel):
    action: Literal["advance", "return", "reject"] = Field(..., description="三态决策")
    result_text: str = Field(..., min_length=0, max_length=4000, description="决策时填写的自由文本")
    actor: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description="决策人 username (向后兼容；服务端以 session 为准)",
    )


def _try_decode_session(request: Request) -> SessionPayload | None:
    """非强制：能拿到 session 就用，拿不到（演示 / 老前端无 cookie）则返回 None。"""
    settings = get_settings()
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return None
    try:
        return jwt_service.decode_session(cookie_value)
    except Exception as exc:
        logger.warning("[api.nodes] session cookie decode failed: %s", exc)
        return None


@router.post("/{flow_id}/nodes/{node_id}/actions")
async def submit_action(
    flow_id: uuid.UUID,
    node_id: uuid.UUID,
    body: SubmitActionRequest,
    request: Request,
    service: Annotated[NodeService, Depends(get_node_service)],
) -> dict[str, Any]:
    """提交三态决策推进节点。

    Bug 2 修复：若请求带 session cookie（前端通过深链已登录），则用 session.sub 覆盖
    body.actor，并校验 session.sub == node.assignee 防止伪装。
    无 cookie 情况下退化为旧行为（actor 信任 body）— 演示环境兼容。
    """
    session = _try_decode_session(request)
    current_user_sub = session.sub if session else None
    current_user_node_id = session.node_id if session else None
    result = await service.submit_action(
        flow_id=flow_id,
        node_id=node_id,
        action=body.action,
        result_text=body.result_text,
        actor=body.actor,
        current_user_sub=current_user_sub,
        current_user_node_id=current_user_node_id,
    )
    return ok(result)
