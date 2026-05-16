"""flow_service: 流程实例的创建 + 查询。

职责：
- create_flow: 写 flow_instances + 写第一条 action_log + upsert apply/manager_review 节点 + 起 LangGraph
- get_flow: 读业务表（不读 checkpoint — 双层状态分离 CONTEXT §3.3）
- list_nodes: 读业务表节点列表
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from offboarding_flow.auth import deep_link, jwt_service
from offboarding_flow.auth.schemas import JWTPayload
from offboarding_flow.config import get_settings
from offboarding_flow.flow_engine.nodes import (
    APPLY_NODE_NAME,
    APPLY_NODE_TITLE,
    MANAGER_REVIEW_NODE_NAME,
    MANAGER_REVIEW_NODE_TITLE,
)
from offboarding_flow.flow_engine.state import OffboardingState
from offboarding_flow.state_store.enums import (
    ActionStatus,
    ActionType,
    NodeStatus,
    Role,
)
from offboarding_flow.state_store.repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
    UserRepository,
)

logger = logging.getLogger(__name__)

# manager_review 默认角色（Phase 4 假设 — Phase 5 接 users 表才能动态查 assignee 角色）
_DEFAULT_MANAGER_ROLE = Role.MANAGER.value
_DEFAULT_MANAGER_DESC = "请审阅离职申请，确认理由并选择 通过 / 退回 / 拒绝。"

# 演示用默认 manager（未接 MM 真实组织关系时的 fallback）
_DEFAULT_MANAGER_USERNAME = "li.si"

# 申请人专属"查看入口"节点 — 让员工可以拿 deep link 进 /my/flows 看进度
APPLICANT_VIEW_NODE_NAME = "applicant_view"
APPLICANT_VIEW_NODE_TITLE = "申请人查看入口"
_APPLICANT_VIEW_DESC = "您的离职流程已启动，可随时点击下方按钮查看当前进度与下一步。"


class FlowService:
    """流程实例服务。"""

    def __init__(
        self,
        session: AsyncSession,
        flow_repo: FlowRepository,
        node_repo: NodeRepository,
        action_repo: ActionRepository,
        graph: Any,  # CompiledStateGraph
        notification_service: Any | None = None,  # NotificationService — Phase 4 注入
    ) -> None:
        self.session = session
        self.flow_repo = flow_repo
        self.node_repo = node_repo
        self.action_repo = action_repo
        self.graph = graph
        self.notification_service = notification_service

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
        # 自动 ensure 演示账号（applicant + manager）— 让 exchange 7 步链能过 user 校验
        user_repo = UserRepository(self.session)
        await user_repo.upsert(
            username=employee_id,
            email=f"{employee_id}@demo.local",
            role=Role.APPLICANT.value,
            display_name=employee_id,
        )
        await user_repo.upsert(
            username=_DEFAULT_MANAGER_USERNAME,
            email=f"{_DEFAULT_MANAGER_USERNAME}@demo.local",
            role=Role.MANAGER.value,
            display_name=_DEFAULT_MANAGER_USERNAME,
        )

        # 提前 upsert apply（自动节点：done）+ manager_review（waiting_human，assignee=li.si）
        # + applicant_view（waiting_human，assignee=申请人，专门给员工点 deep link 进入）
        await self.node_repo.upsert(
            flow_id=flow.id,
            node_name=APPLY_NODE_NAME,
            node_title=APPLY_NODE_TITLE,
            status=NodeStatus.DONE,
        )
        manager_node = await self.node_repo.upsert(
            flow_id=flow.id,
            node_name=MANAGER_REVIEW_NODE_NAME,
            node_title=MANAGER_REVIEW_NODE_TITLE,
            status=NodeStatus.WAITING_HUMAN,
            assignee=_DEFAULT_MANAGER_USERNAME,
        )
        applicant_view_node = await self.node_repo.upsert(
            flow_id=flow.id,
            node_name=APPLICANT_VIEW_NODE_NAME,
            node_title=APPLICANT_VIEW_NODE_TITLE,
            status=NodeStatus.WAITING_HUMAN,
            assignee=employee_id,
        )

        # Phase 4 Slice 4A: outbox 入队 manager_review email（事务内一致提交，REQ-NOTI-01/04）
        # 失败仅 log warning 不阻断主链路（双通道：Mattermost 还在 Slice 4B）
        if self.notification_service is not None and manager_node is not None:
            manager_token, manager_payload = self._build_node_token(
                flow_id=flow.id,
                node=manager_node,
                role=Role.MANAGER.value,
                allowed_actions=["advance", "return", "reject"],
            )
            try:
                await self.notification_service.enqueue_node_email(
                    flow_id=flow.id,
                    node_state_id=manager_node.id,
                    node_name=MANAGER_REVIEW_NODE_NAME,
                    node_title=MANAGER_REVIEW_NODE_TITLE,
                    node_description=_DEFAULT_MANAGER_DESC,
                    assignee_username=_DEFAULT_MANAGER_USERNAME,
                    assignee_email=f"{_DEFAULT_MANAGER_USERNAME}@demo.local",
                    assignee_role=_DEFAULT_MANAGER_ROLE,
                    employee_name=employee_id,
                    deep_link_payload=manager_payload,
                    deep_link_token=manager_token,
                )
            except Exception as enqueue_exc:
                logger.warning(
                    "[flow_service] manager outbox enqueue failed (non-fatal) flow=%s: %s",
                    flow.id,
                    enqueue_exc,
                )

        # 申请人"开始"邮件 — target applicant_view 节点（PRD §6.2 / §7.4）
        if self.notification_service is not None and applicant_view_node is not None:
            applicant_token, applicant_payload = self._build_node_token(
                flow_id=flow.id,
                node=applicant_view_node,
                role=Role.APPLICANT.value,
                allowed_actions=[],
            )
            try:
                await self.notification_service.enqueue_node_email(
                    flow_id=flow.id,
                    node_state_id=applicant_view_node.id,
                    node_name=APPLICANT_VIEW_NODE_NAME,
                    node_title=APPLICANT_VIEW_NODE_TITLE,
                    node_description=_APPLICANT_VIEW_DESC,
                    assignee_username=employee_id,
                    assignee_email=f"{employee_id}@demo.local",
                    assignee_role=Role.APPLICANT.value,
                    employee_name=employee_id,
                    deep_link_payload=applicant_payload,
                    deep_link_token=applicant_token,
                )
            except Exception as enqueue_exc:
                logger.warning(
                    "[flow_service] applicant kickoff email enqueue failed flow=%s: %s",
                    flow.id,
                    enqueue_exc,
                )

        # 提交业务事务
        await self.session.commit()

        # Phase 4 Slice 4D: commit 后立即唤醒 outbox worker（in-process 事件驱动，非轮询）
        try:
            from offboarding_flow.workers.outbox_drain import signal_outbox_pending

            signal_outbox_pending()
        except Exception as sig_exc:
            logger.debug("[flow_service] signal_outbox_pending no-op: %s", sig_exc)

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

        # Step 4: 给申请人签一个 applicant_view 节点的一键登录 deep link（演示用）
        applicant_deep_link = self._issue_applicant_deep_link(
            flow_id=flow.id,
            applicant_view_node_id=(applicant_view_node.id if applicant_view_node else None),
            employee_id=employee_id,
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
            "applicant_deep_link": applicant_deep_link,
        }

    def _build_node_token(
        self,
        *,
        flow_id: uuid.UUID,
        node: Any,
        role: str,
        allowed_actions: list[str],
    ) -> tuple[str, JWTPayload]:
        """构造节点对应的 JWT token + payload。"""
        settings = get_settings()
        now = int(time.time())
        username = node.assignee or "unknown"
        payload = JWTPayload(
            sub=username,
            email=f"{username}@demo.local",
            role=role,
            flow_id=flow_id,
            node_id=node.id,
            node_name=node.node_name,
            allowed_actions=allowed_actions,
            iat=now,
            exp=now + settings.token_expiry_hours * 3600,
            jti=uuid.uuid4().hex,
        )
        return jwt_service.encode(payload), payload

    def _issue_applicant_deep_link(
        self,
        *,
        flow_id: uuid.UUID,
        applicant_view_node_id: uuid.UUID | None,
        employee_id: str,
    ) -> str | None:
        """签 applicant_view 节点深链 token（演示便利：起流程立即拿到登录链接）。

        返回完整 `/flow/handle?...` URL。失败仅 log 不抛（不阻断主链路）。
        """
        if applicant_view_node_id is None:
            return None
        try:
            settings = get_settings()
            now = int(time.time())
            payload = JWTPayload(
                sub=employee_id,
                email=f"{employee_id}@demo.local",
                role=Role.APPLICANT.value,
                flow_id=flow_id,
                node_id=applicant_view_node_id,
                node_name=APPLICANT_VIEW_NODE_NAME,
                allowed_actions=[],
                iat=now,
                exp=now + settings.token_expiry_hours * 3600,
                jti=uuid.uuid4().hex,
            )
            token = jwt_service.encode(payload)
            return deep_link.build_deep_link(token, payload, base_url=settings.deeplink_base_url)
        except Exception as exc:
            logger.warning("[flow_service] issue applicant deep link failed: %s", exc)
            return None

    async def list_flows(self, limit: int = 50) -> list[dict[str, Any]]:
        """HR Dashboard 用：返回所有流程实例（含当前节点 + assignee）。"""
        flows = await self.flow_repo.list_all(limit=limit)
        result: list[dict[str, Any]] = []
        for flow in flows:
            nodes = await self.node_repo.list_by_flow(flow.id)
            current = next((n for n in nodes if n.status == "active"), None)
            result.append(
                {
                    "flow_id": str(flow.id),
                    "employee_id": flow.employee_id,
                    "template": flow.template,
                    "status": flow.status,
                    "started_at": flow.started_at.isoformat() if flow.started_at else None,
                    "completed_at": (flow.completed_at.isoformat() if flow.completed_at else None),
                    "node_count": len(nodes),
                    "current_node": (
                        {
                            "name": current.node_name,
                            "title": current.node_title,
                            "assignee": current.assignee,
                        }
                        if current is not None
                        else None
                    ),
                }
            )
        return result

    async def get_flow(self, flow_id: uuid.UUID) -> dict[str, Any] | None:
        """读业务表返回流程状态（不读 LangGraph checkpoint — 双层状态分离）。"""
        flow = await self.flow_repo.get(flow_id)
        if flow is None:
            return None
        nodes = await self.node_repo.list_by_flow(flow_id)
        ctx = flow.context or {}
        return {
            "flow_id": str(flow.id),
            "employee_id": flow.employee_id,
            "template": flow.template,
            "status": flow.status,
            "started_at": flow.started_at.isoformat() if flow.started_at else None,
            "completed_at": (flow.completed_at.isoformat() if flow.completed_at else None),
            "node_count": len(nodes),
            # Phase 2: 暴露 handover docs + final summary doc 给前端展示
            "handover_docs": ctx.get("handover_docs", []),
            "final_summary_doc": ctx.get("final_summary_doc"),
            "node_results": ctx.get("node_results", []),
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
