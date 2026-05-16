"""node_service: 节点决策推进。

职责：
- submit_action: 三态决策推进，执行双写规范（业务事务 commit → graph.ainvoke Command resume）
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import HTTPException
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.state_store.enums import (
    ActionStatus,
    ActionType,
    FlowStatus,
    NodeStatus,
)
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
)

logger = logging.getLogger(__name__)

# action 字符串 → (ActionType, 新 NodeStatus) 映射
_ACTION_MAP: dict[str, tuple[ActionType, NodeStatus]] = {
    "advance": (ActionType.ADVANCE, NodeStatus.DONE),
    "return": (ActionType.RETURN, NodeStatus.RETURNED),
    "reject": (ActionType.REJECT, NodeStatus.REJECTED),
}


class NodeService:
    """节点推进服务。"""

    def __init__(
        self,
        session: AsyncSession,
        flow_repo: FlowRepository,
        node_repo: NodeRepository,
        action_repo: ActionRepository,
        graph: Any,
    ) -> None:
        self.session = session
        self.flow_repo = flow_repo
        self.node_repo = node_repo
        self.action_repo = action_repo
        self.graph = graph

    async def submit_action(
        self,
        flow_id: uuid.UUID,
        node_id: uuid.UUID,
        action: str,
        result_text: str,
        actor: str,
    ) -> dict[str, Any]:
        """提交三态决策推进节点。

        双写规范（Phase 1 最小版 — PRD §5.3 Pattern 1 + CONTEXT §4）：
        1. 业务事务：
           - 校验节点存在 + status=waiting_human（409 if not）
           - INSERT action_log
           - UPDATE node_states.status = done/rejected/returned + result_text + completed_at
           - 若 advance：flow_instances.status = completed（Phase 1 简化：manager_review 是末节点）
           - 若 reject：flow_instances.status = rejected
        2. session.commit()
        3. graph.ainvoke(Command(resume={action, result_text, actor}))
        4. graph 失败仅 log（Phase 2 加 mark action_log.failed + recover）
        """
        if action not in _ACTION_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"action 必须是 advance/return/reject，收到: {action}",
            )

        # Step 1: 业务校验 + 事务
        node = await self.node_repo.get(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail=f"node_id {node_id} 不存在")
        if str(node.flow_id) != str(flow_id):
            raise HTTPException(
                status_code=400,
                detail=f"node {node_id} 不属于 flow {flow_id}",
            )
        if node.status != NodeStatus.WAITING_HUMAN.value:
            raise HTTPException(
                status_code=409,
                detail=f"节点状态为 {node.status}，只能在 waiting_human 时推进",
            )

        action_type, new_status = _ACTION_MAP[action]
        previous_status = node.status

        # 写 action_log
        await self.action_repo.create(
            flow_id=flow_id,
            node_state_id=node_id,
            actor=actor,
            action=action_type,
            result_text=result_text,
            status=ActionStatus.SUCCESS,
        )

        # 更新 node_states
        await self.node_repo.complete(node_id, result_text, new_status)

        # Phase 1: manager_review 是末节点 — advance 流程 completed，reject 流程 rejected
        if action == "reject":
            await self.flow_repo.mark_completed(flow_id, status=FlowStatus.REJECTED)
        elif action == "advance":
            await self.flow_repo.mark_completed(flow_id, status=FlowStatus.COMPLETED)
        # 'return' 在 Phase 1 manager_review 是首人工节点，无上游可退 — 仅记录不改流程状态

        # 提交业务事务
        await self.session.commit()
        logger.info(
            "[node_service] flow=%s node=%s action=%s — business committed",
            flow_id,
            node_id,
            action,
        )

        # Step 2: 推进 graph（事务已 commit — 失败仅 log，Phase 2 加重试）
        config = {"configurable": {"thread_id": str(flow_id)}}
        try:
            await self.graph.ainvoke(
                Command(
                    resume={
                        "action": action,
                        "result_text": result_text,
                        "actor": actor,
                    }
                ),
                config=config,
            )
            logger.info("[node_service] graph resumed flow=%s action=%s", flow_id, action)
        except Exception as e:
            logger.exception("[node_service] graph.ainvoke failed AFTER business commit: %s", e)
            # Phase 2 才加：mark action_log.failed + alert + recover 脚本

        # Step 3: 重读最新流程状态
        flow = await self.flow_repo.get(flow_id)

        return {
            "node_id": str(node_id),
            "previous_status": previous_status,
            "new_status": new_status.value,
            "current_action": action,
            "flow_status": flow.status if flow else "unknown",
            "next_node": None,  # Phase 2 才有 next_node
        }
