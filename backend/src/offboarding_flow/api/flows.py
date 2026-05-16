"""POST /api/flows + GET /api/flows/{id} + GET /api/flows/{id}/nodes 路由。"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from offboarding_flow.api.deps import get_flow_service
from offboarding_flow.api.envelope import ok
from offboarding_flow.services import FlowService

router = APIRouter(prefix="/api/flows", tags=["flows"])


class CreateFlowRequest(BaseModel):
    employee_id: str = Field(..., min_length=1, max_length=64, description="离职员工 username")
    context: dict | None = Field(default=None, description="额外业务上下文")


@router.post("")
async def create_flow(
    body: CreateFlowRequest,
    service: Annotated[FlowService, Depends(get_flow_service)],
) -> dict[str, Any]:
    """创建离职流程实例，启动 graph 跑到 manager_review interrupt。"""
    result = await service.create_flow(employee_id=body.employee_id, context=body.context)
    return ok(result)


@router.get("/{flow_id}")
async def get_flow(
    flow_id: uuid.UUID,
    service: Annotated[FlowService, Depends(get_flow_service)],
) -> dict[str, Any]:
    result = await service.get_flow(flow_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"flow {flow_id} 不存在")
    return ok(result)


@router.get("/{flow_id}/nodes")
async def list_flow_nodes(
    flow_id: uuid.UUID,
    service: Annotated[FlowService, Depends(get_flow_service)],
) -> dict[str, Any]:
    # 先确认 flow 存在
    flow = await service.get_flow(flow_id)
    if flow is None:
        raise HTTPException(status_code=404, detail=f"flow {flow_id} 不存在")
    nodes = await service.list_nodes(flow_id)
    return ok(nodes, meta={"count": len(nodes)})
