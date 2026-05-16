"""业务表 Repository 层（双写规范的"业务侧"承担方）。

关键约定（CONTEXT §3.4 + PITFALLS #16）：
- 所有"会被节点函数调用"的写入用 upsert（PG ON CONFLICT），防 LangGraph interrupt
  重跑节点函数时重复写入
- 所有方法接收 AsyncSession 注入（FastAPI Depends 友好）
- 所有方法返回 ORM 实例（不返回 dict，保留 type 信息）
- 不主动 commit — 交给调用方控制事务边界（service 层）
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import ActionStatus, ActionType, FlowStatus, NodeStatus
from .models import ActionLog, FlowInstance, NodeState, User


# ---------------------------------------------------------------------------
# FlowRepository
# ---------------------------------------------------------------------------
class FlowRepository:
    """flow_instances 表 Repository。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        employee_id: str,
        template: str = "standard_offboarding",
        context: dict | None = None,
    ) -> FlowInstance:
        """创建新流程实例。"""
        flow = FlowInstance(
            employee_id=employee_id,
            template=template,
            status=FlowStatus.IN_PROGRESS.value,
            context=context or {},
        )
        self.session.add(flow)
        await self.session.flush()
        await self.session.refresh(flow)
        return flow

    async def get(self, flow_id: uuid.UUID) -> FlowInstance | None:
        return await self.session.get(FlowInstance, flow_id)

    async def list_all(self, limit: int = 50) -> list[FlowInstance]:
        stmt = select(FlowInstance).order_by(FlowInstance.started_at.desc()).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_completed(
        self, flow_id: uuid.UUID, status: FlowStatus = FlowStatus.COMPLETED
    ) -> None:
        stmt = (
            update(FlowInstance)
            .where(FlowInstance.id == flow_id)
            .values(status=status.value, completed_at=func.now())
        )
        await self.session.execute(stmt)

    async def append_node_result(self, flow_id: uuid.UUID, result: dict) -> None:
        """向 flow_instances.context.node_results JSONB 数组追加一条节点结果。

        策略 B（02-01-PLAN Task 1）：应用层读改写 + SELECT FOR UPDATE 防并发。
        Phase 2 流程内单实例并发量低（每次决策一个 service 实例），FOR UPDATE 即可。
        """
        stmt = select(FlowInstance).where(FlowInstance.id == flow_id).with_for_update()
        result_row = await self.session.execute(stmt)
        flow = result_row.scalar_one()
        # 深拷贝防 SQLAlchemy 不识别 mutation
        context = dict(flow.context or {})
        results = list(context.get("node_results", []))
        results.append(result)
        context["node_results"] = results
        flow.context = context
        await self.session.flush()


# ---------------------------------------------------------------------------
# NodeRepository
# ---------------------------------------------------------------------------
class NodeRepository:
    """node_states 表 Repository（含 upsert 幂等接口）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        flow_id: uuid.UUID,
        node_name: str,
        node_title: str,
        status: NodeStatus,
        assignee: str | None = None,
    ) -> NodeState:
        """幂等创建 / 更新节点状态。

        PITFALLS #16: LangGraph interrupt 重跑节点函数时，本方法被多次调用必须不报错。
        用 PG ON CONFLICT (flow_id, node_name) 实现。
        """
        stmt = (
            pg_insert(NodeState)
            .values(
                flow_id=flow_id,
                node_name=node_name,
                node_title=node_title,
                status=status.value,
                assignee=assignee,
                entered_at=func.now(),
            )
            .on_conflict_do_update(
                index_elements=["flow_id", "node_name"],
                set_={
                    "status": status.value,
                    "assignee": assignee,
                    "updated_at": func.now(),
                },
            )
            .returning(NodeState)
        )
        result = await self.session.execute(stmt)
        # ON CONFLICT DO UPDATE returning 必须用 scalar_one
        node = result.scalar_one()
        return node

    async def get(self, node_id: uuid.UUID) -> NodeState | None:
        return await self.session.get(NodeState, node_id)

    async def list_by_flow(self, flow_id: uuid.UUID) -> list[NodeState]:
        stmt = select(NodeState).where(NodeState.flow_id == flow_id).order_by(NodeState.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def complete(
        self,
        node_id: uuid.UUID,
        result_text: str | None,
        new_status: NodeStatus = NodeStatus.DONE,
    ) -> NodeState | None:
        """标记节点完成（done/rejected/returned），写入 result_text。"""
        stmt = (
            update(NodeState)
            .where(NodeState.id == node_id)
            .values(
                status=new_status.value,
                result_text=result_text,
                completed_at=func.now(),
                updated_at=func.now(),
            )
            .returning(NodeState)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# ActionRepository
# ---------------------------------------------------------------------------
class ActionRepository:
    """action_logs 表 Repository（append-only）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        flow_id: uuid.UUID,
        actor: str,
        action: ActionType,
        node_state_id: uuid.UUID | None = None,
        result_text: str | None = None,
        status: ActionStatus = ActionStatus.SUCCESS,
        error_message: str | None = None,
        payload: dict | None = None,
    ) -> ActionLog:
        log = ActionLog(
            flow_id=flow_id,
            node_state_id=node_state_id,
            actor=actor,
            action=action.value,
            result_text=result_text,
            status=status.value,
            error_message=error_message,
            payload=payload,
        )
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def list_by_flow(self, flow_id: uuid.UUID) -> list[ActionLog]:
        stmt = select(ActionLog).where(ActionLog.flow_id == flow_id).order_by(ActionLog.created_at)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_failed(self, action_id: uuid.UUID, error_message: str) -> None:
        """标记 action_log 为失败 + 写入错误信息（双写补偿入口）。"""
        stmt = (
            update(ActionLog)
            .where(ActionLog.id == action_id)
            .values(
                status=ActionStatus.FAILED.value,
                error_message=error_message,
            )
        )
        await self.session.execute(stmt)

    async def mark_success(self, action_id: uuid.UUID) -> None:
        """标记 action_log 为成功（PENDING / FAILED 都可转 SUCCESS）。"""
        stmt = (
            update(ActionLog)
            .where(ActionLog.id == action_id)
            .values(
                status=ActionStatus.SUCCESS.value,
                error_message=None,
            )
        )
        await self.session.execute(stmt)

    async def list_failed(
        self,
        limit: int = 100,
        flow_id: uuid.UUID | None = None,
    ) -> list[ActionLog]:
        """查询所有 failed 状态 action_log（recover 脚本入口）。"""
        stmt = select(ActionLog).where(ActionLog.status == ActionStatus.FAILED.value)
        if flow_id is not None:
            stmt = stmt.where(ActionLog.flow_id == flow_id)
        stmt = stmt.order_by(ActionLog.created_at).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# UserRepository
# ---------------------------------------------------------------------------
class UserRepository:
    """users 表 Repository（Phase 4 seed 才大量使用）。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        username: str,
        email: str,
        role: str,
        display_name: str | None = None,
        department: str | None = None,
        manager_email: str | None = None,
    ) -> User:
        stmt = (
            pg_insert(User)
            .values(
                username=username,
                email=email,
                role=role,
                display_name=display_name,
                department=department,
                manager_email=manager_email,
            )
            .on_conflict_do_update(
                index_elements=["username"],
                set_={
                    "email": email,
                    "role": role,
                    "display_name": display_name,
                    "department": department,
                    "manager_email": manager_email,
                    "updated_at": func.now(),
                },
            )
            .returning(User)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
