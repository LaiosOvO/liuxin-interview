"""POST /api/flows/{flow_id}/nodes/{node_id}/actions 路由。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from offboarding_flow.api.deps import get_node_service
from offboarding_flow.api.envelope import ok
from offboarding_flow.services import NodeService

router = APIRouter(prefix="/api/flows", tags=["nodes"])


class SubmitActionRequest(BaseModel):
    action: Literal["advance", "return", "reject"] = Field(..., description="三态决策")
    result_text: str = Field(..., min_length=0, max_length=4000, description="决策时填写的自由文本")
    actor: str = Field(..., min_length=1, max_length=64, description="决策人 username")


@router.post("/{flow_id}/nodes/{node_id}/actions")
async def submit_action(
    flow_id: uuid.UUID,
    node_id: uuid.UUID,
    body: SubmitActionRequest,
    service: Annotated[NodeService, Depends(get_node_service)],
) -> dict[str, Any]:
    """提交三态决策推进节点。"""
    result = await service.submit_action(
        flow_id=flow_id,
        node_id=node_id,
        action=body.action,
        result_text=body.result_text,
        actor=body.actor,
    )
    return ok(result)
