"""flow_service: 流程实例的创建 + 查询。

职责：
- create_flow: 写 flow_instances + 写第一条 action_log + upsert apply/manager_review 节点 + 起 LangGraph
- get_flow: 读业务表（不读 checkpoint — 双层状态分离 CONTEXT §3.3）
- list_nodes: 读业务表节点列表
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.flow_engine.nodes import (
    APPLY_NODE_NAME,
    APPLY_NODE_TITLE,
    MANAGER_REVIEW_NODE_NAME,
    MANAGER_REVIEW_NODE_TITLE,
)
from offboarding_flow.flow_engine.state import OffboardingState
from offboarding_flow.state_store.enums import ActionStatus, ActionType, NodeStatus
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
)

logger = logging.getLogger(__name__)


class FlowService:
    """流程实例服务。"""

    def __init__(
        self,
        session: AsyncSession,
        flow_repo: FlowRepository,
        node_repo: NodeRepository,
        action_repo: ActionRepository,
        graph: Any,  # CompiledStateGraph
    ) -> None:
        self.session = session
        self.flow_repo = flow_repo
        self.node_repo = node_repo
        self.action_repo = action_repo
        self.graph = graph

    async def create_flow(
        self,
        employee_id: str,
        context: dict | None = None,
    ) -> dict[str, Any]:
        """起一个新流程。

        双写规范（Phase 1 最小版 — PRD §5.3 Pattern 1）：
        1. 业务事务：
           - INSERT flow_instances
           - INSERT action_log (action=system, actor=system:bootstrap)
           - upsert node_states (apply=done, manager_review=waiting_human)
        2. session.commit()
        3. graph.ainvoke 跑到 manager_review interrupt 挂起
        """
        # Step 1: 业务事务
        flow = await self.flow_repo.create(employee_id=employee_id, context=context or {})
        await self.action_repo.create(
            flow_id=flow.id,
            actor="system:bootstrap",
            action=ActionType.SYSTEM,
            status=ActionStatus.SUCCESS,
            payload={"event": "flow_created", "employee_id": employee_id},
        )
        # 提前 upsert apply（自动节点：done）+ manager_review（waiting_human）
        # 节点函数 interrupt 重跑时这两次 upsert 不会重复
        await self.node_repo.upsert(
            flow_id=flow.id,
            node_name=APPLY_NODE_NAME,
            node_title=APPLY_NODE_TITLE,
            status=NodeStatus.DONE,
        )
        await self.node_repo.upsert(
            flow_id=flow.id,
            node_name=MANAGER_REVIEW_NODE_NAME,
            node_title=MANAGER_REVIEW_NODE_TITLE,
            status=NodeStatus.WAITING_HUMAN,
        )

        # 提交业务事务
        await self.session.commit()

        # Step 2: 启动 graph — 跑到 manager_review interrupt 挂起
        initial_state: OffboardingState = {
            "flow_id": str(flow.id),
            "employee_id": employee_id,
            "current_action": None,
            "node_results": [],
            "context": context or {},
        }
        config = {"configurable": {"thread_id": str(flow.id)}}
        try:
            await self.graph.ainvoke(initial_state, config=config)
            logger.info("[flow_service] flow %s started, interrupted at manager_review", flow.id)
        except Exception as e:
            logger.exception("[flow_service] graph.ainvoke failed for flow %s: %s", flow.id, e)
            # Phase 2 才加：mark action_log.failed + recover 脚本
            raise

        # Step 3: 查询当前节点状态返回
        nodes = await self.node_repo.list_by_flow(flow.id)
        current_node = next(
            (n for n in nodes if n.status == NodeStatus.WAITING_HUMAN.value),
            None,
        )

        return {
            "flow_id": str(flow.id),
            "employee_id": flow.employee_id,
            "status": flow.status,
            "started_at": flow.started_at.isoformat() if flow.started_at else None,
            "current_node": (
                {
                    "id": str(current_node.id),
                    "name": current_node.node_name,
                    "title": current_node.node_title,
                    "status": current_node.status,
                    "assignee": current_node.assignee,
                }
                if current_node
                else None
            ),
        }

    async def get_flow(self, flow_id: uuid.UUID) -> dict[str, Any] | None:
        """读业务表返回流程状态（不读 LangGraph checkpoint — 双层状态分离）。"""
        flow = await self.flow_repo.get(flow_id)
        if flow is None:
            return None
        nodes = await self.node_repo.list_by_flow(flow_id)
        return {
            "flow_id": str(flow.id),
            "employee_id": flow.employee_id,
            "template": flow.template,
            "status": flow.status,
            "started_at": flow.started_at.isoformat() if flow.started_at else None,
            "completed_at": (flow.completed_at.isoformat() if flow.completed_at else None),
            "node_count": len(nodes),
        }

    async def list_nodes(self, flow_id: uuid.UUID) -> list[dict[str, Any]]:
        """读业务表 node_states 列表。"""
        nodes = await self.node_repo.list_by_flow(flow_id)
        return [
            {
                "id": str(n.id),
                "name": n.node_name,
                "title": n.node_title,
                "status": n.status,
                "assignee": n.assignee,
                "result_text": n.result_text,
                "is_overdue": n.is_overdue,
                "entered_at": n.entered_at.isoformat() if n.entered_at else None,
                "completed_at": n.completed_at.isoformat() if n.completed_at else None,
            }
            for n in nodes
        ]
