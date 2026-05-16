"""auto_node_service: AutoNode 双写 helper（PRD §18 加分项 — Phase 4.5）。

职责：
- execute_auto_action: 自动节点双写规范（与 NodeService.submit_action 架构对称）
  - 业务事务：upsert node_states (status=done) + INSERT action_log + append flow.context.node_results
  - 由节点函数在外部 API 调成功后调用
  - 失败路径（外部 API 抛错）：节点函数捕获后调 execute_auto_action(action_status=FAILED, error_message=...)
    然后 raise — 让 graph.ainvoke 失败、流程卡住等运维介入

与 NodeService 差异：
- 无 interrupt → 无人工决策来源；actor 默认 system:auto
- 不直接 invoke graph（节点函数内已经在 graph 上下文）
- 不做 jti token 失效（自动节点无 token）
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.state_store.enums import (
    ActionStatus,
    ActionType,
    NodeStatus,
)
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
)

logger = logging.getLogger(__name__)


def _default_session_factory() -> AbstractAsyncContextManager[AsyncSession]:
    """默认 session_factory（延迟 import 防循环依赖）。"""
    from offboarding_flow.state_store.session import new_session

    return new_session()


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class AutoNodeService:
    """AutoNode 双写服务（与 NodeService.submit_action 架构对称）。

    用法（节点函数内）：
        svc = AutoNodeService()
        # 成功路径
        await svc.execute_auto_action(
            flow_id=flow_id,
            node_name="auto_archive_to_storage",
            node_title="自动归档（外部存储）",
            result_text="...",
            action_status=ActionStatus.SUCCESS,
        )
        # 失败路径
        await svc.execute_auto_action(
            flow_id=flow_id,
            node_name="...",
            node_title="...",
            action_status=ActionStatus.FAILED,
            error_message="...",
        )
    """

    def __init__(self, session_factory: SessionFactory | None = None) -> None:
        self.session_factory: SessionFactory = session_factory or _default_session_factory

    async def execute_auto_action(
        self,
        flow_id: uuid.UUID,
        node_name: str,
        node_title: str,
        actor: str = "system:auto",
        result_text: str = "",
        action_status: ActionStatus = ActionStatus.SUCCESS,
        error_message: str | None = None,
        payload: dict | None = None,
    ) -> None:
        """自动节点双写（在节点函数内部调用）。

        - action_status=SUCCESS：node_states upsert status=done + append node_results
        - action_status=FAILED：仅 INSERT action_log（status=failed）+ 不动 node_states
          （让 recover 脚本或运维介入；节点不强行标 done）
        """
        async with self.session_factory() as session:
            flow_repo = FlowRepository(session)
            node_repo = NodeRepository(session)
            action_repo = ActionRepository(session)

            if action_status == ActionStatus.SUCCESS:
                # 1) upsert node_states → status=done（幂等 PG ON CONFLICT）
                await node_repo.upsert(
                    flow_id=flow_id,
                    node_name=node_name,
                    node_title=node_title,
                    status=NodeStatus.DONE,
                    assignee=actor,
                )
                # 2) INSERT action_log (SYSTEM + SUCCESS, actor=system:auto)
                await action_repo.create(
                    flow_id=flow_id,
                    actor=actor,
                    action=ActionType.SYSTEM,
                    result_text=result_text,
                    status=ActionStatus.SUCCESS,
                    payload=payload,
                )
                # 3) 追加 flow.context.node_results（前端 / 邮件 / 时间线渲染都用）
                await flow_repo.append_node_result(
                    flow_id=flow_id,
                    result={
                        "node_name": node_name,
                        "node_title": node_title,
                        "result_text": result_text,
                        "actor": actor,
                        "completed_at": datetime.now(UTC).isoformat(),
                        "action": "advance",  # AutoNode 总是 advance
                    },
                )
                await session.commit()
                logger.info(
                    "[auto_node_service] auto action SUCCESS — flow=%s node=%s",
                    flow_id,
                    node_name,
                )
            else:
                # 失败路径：仅 action_log failed + 不标 node done（让 recover 处理）
                await action_repo.create(
                    flow_id=flow_id,
                    actor=actor,
                    action=ActionType.SYSTEM,
                    result_text=result_text or "auto action failed",
                    status=ActionStatus.FAILED,
                    error_message=error_message,
                    payload=payload,
                )
                await session.commit()
                logger.warning(
                    "[auto_node_service] auto action FAILED — flow=%s node=%s err=%s",
                    flow_id,
                    node_name,
                    error_message,
                )
