"""node_service: 节点决策推进（Phase 2 完整版双写规范）。

职责：
- submit_action: 三态决策推进，执行双写规范完整版（业务事务 commit → graph.ainvoke → 失败补偿）

双写规范（PRD §5.3.1 + PITFALLS #2 + 02-CONTEXT §5）：
1. 业务校验（节点存在 + status=waiting_human）
2. 业务事务：
   - INSERT action_log (status=PENDING)
   - UPDATE node_states (done/rejected/returned + result_text + completed_at)
   - append flow_instances.context.node_results JSONB 数组
   - 若 reject：flow_instances.status=rejected
3. session.commit() — 业务侧 source of truth 已固化
4. graph.ainvoke(Command(resume={...})) 推进 LangGraph
5. 失败（graph 异常）→ 新 session mark action_log.failed + raise HTTPException(500)
6. 成功 → 新 session mark action_log.success
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.auth import jti_service
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

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# action 字符串 → (ActionType, 新 NodeStatus) 映射
_ACTION_MAP: dict[str, tuple[ActionType, NodeStatus]] = {
    "advance": (ActionType.ADVANCE, NodeStatus.DONE),
    "return": (ActionType.RETURN, NodeStatus.RETURNED),
    "reject": (ActionType.REJECT, NodeStatus.REJECTED),
}


# 默认 session_factory — 测试时可注入 mock
def _default_session_factory() -> AbstractAsyncContextManager[AsyncSession]:
    """默认 session_factory（导入时延迟避免循环依赖）。"""
    from offboarding_flow.state_store.session import new_session

    return new_session()


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class NodeService:
    """节点推进服务（Phase 2 完整双写规范）。"""

    def __init__(
        self,
        session: AsyncSession,
        flow_repo: FlowRepository,
        node_repo: NodeRepository,
        action_repo: ActionRepository,
        graph: Any,
        session_factory: SessionFactory | None = None,
        redis: "Redis | None" = None,
    ) -> None:
        self.session = session
        self.flow_repo = flow_repo
        self.node_repo = node_repo
        self.action_repo = action_repo
        self.graph = graph
        # 用 _default_session_factory 默认值（测试可注入 mock）
        self.session_factory: SessionFactory = session_factory or _default_session_factory
        self.redis = redis

    async def submit_action(
        self,
        flow_id: uuid.UUID,
        node_id: uuid.UUID,
        action: str,
        result_text: str,
        actor: str,
    ) -> dict[str, Any]:
        """提交三态决策推进节点（Phase 2 双写规范完整版）。"""
        if action not in _ACTION_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"action 必须是 advance/return/reject，收到: {action}",
            )

        # ---- Step 1: 业务校验 ----
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
        node_name = node.node_name
        node_title = node.node_title

        # ---- Step 2: 业务事务 ----
        # 2a. action_log (PENDING)
        action_log = await self.action_repo.create(
            flow_id=flow_id,
            node_state_id=node_id,
            actor=actor,
            action=action_type,
            result_text=result_text,
            status=ActionStatus.PENDING,
        )

        # 2b. node_states 完成
        await self.node_repo.complete(node_id, result_text, new_status)

        # 2c. flow_instances.context.node_results 追加（业务侧冗余）
        await self.flow_repo.append_node_result(
            flow_id=flow_id,
            result={
                "node_name": node_name,
                "node_title": node_title,
                "result_text": result_text,
                "actor": actor,
                "completed_at": datetime.now(UTC).isoformat(),
                "action": action,
            },
        )

        # 2d. reject → flow.status=rejected（advance/return 不在此处改 flow 状态，由 graph 走完后判断）
        if action == "reject":
            await self.flow_repo.mark_completed(flow_id, status=FlowStatus.REJECTED)

        # ---- Step 3: 提交业务事务 ----
        await self.session.commit()
        logger.info(
            "[node_service] flow=%s node=%s action=%s — business committed",
            flow_id,
            node_id,
            action,
        )

        # ---- Step 3.5 (Phase 3): 节点状态变更后失效该 node 所有未消费 token（PRD §6.2.3）----
        if self.redis is not None:
            try:
                invalidated = await jti_service.invalidate_node_tokens(self.redis, node_id)
                if invalidated > 0:
                    logger.info(
                        "[node_service] invalidated %d tokens for node=%s",
                        invalidated,
                        node_id,
                    )
            except Exception as e:
                logger.warning(
                    "[node_service] invalidate tokens failed (non-fatal) flow=%s node=%s err=%s",
                    flow_id,
                    node_id,
                    e,
                )

        # ---- Step 4: 推进 graph（失败时新 session mark failed + raise）----
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
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "[node_service] graph.ainvoke FAILED after business commit — flow=%s action_log=%s: %s",
                flow_id,
                action_log.id,
                error_msg,
            )
            # 失败补偿：新 session 标 action_log failed
            try:
                async with self.session_factory() as fail_session:
                    fail_action_repo = ActionRepository(fail_session)
                    await fail_action_repo.mark_failed(action_log.id, error_msg)
                    await fail_session.commit()
            except Exception as fail_exc:
                # 失败补偿本身失败 — 仅 log，不掩盖原异常
                logger.error(
                    "[node_service] mark_failed also failed for action_log=%s: %s",
                    action_log.id,
                    fail_exc,
                )
            # 暂存当前 flow 数据后 raise
            raise HTTPException(
                status_code=500,
                detail=(
                    f"流程推进失败已记录 action_log={action_log.id}，"
                    f"可通过 scripts/recover_from_db.py --flow-id={flow_id} 重试 ({error_msg})"
                ),
            ) from exc

        # ---- Step 5: 成功 → mark action_log success + 若 graph 到 END 则 mark flow completed ----
        # 注意：mark_success 用主 session（self.action_repo）— 失败补偿路径才用 session_factory
        # 因为成功路径下原 session 仍有效，且 commit 后可以再 commit
        try:
            await self.action_repo.mark_success(action_log.id)
            # 检查 graph 是否到 END（snapshot.next 为空）
            try:
                snapshot = await self.graph.aget_state(config)
                next_nodes = list(snapshot.next or [])
                if not next_nodes and action != "reject":
                    # graph 推进到 END 且不是 reject → flow completed
                    await self.flow_repo.mark_completed(flow_id, status=FlowStatus.COMPLETED)
            except Exception as snap_exc:
                logger.warning("[node_service] aget_state failed (non-fatal): %s", snap_exc)
            await self.session.commit()
        except Exception as ok_exc:
            # 仅 log — 不阻塞返回（graph 推进已成功，action_log 状态轻微不一致可被 recover 修）
            logger.warning(
                "[node_service] mark_success failed for action_log=%s: %s",
                action_log.id,
                ok_exc,
            )

        # ---- Step 6: 重读最新流程状态 ----
        flow = await self.flow_repo.get(flow_id)

        return {
            "node_id": str(node_id),
            "node_name": node_name,
            "previous_status": previous_status,
            "new_status": new_status.value,
            "current_action": action,
            "flow_status": flow.status if flow else "unknown",
            "action_log_id": str(action_log.id),
            "next_node": None,  # Phase 2 Plan 05 才接入 graph snapshot.next
        }
