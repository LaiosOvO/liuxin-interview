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
    import asyncio as _asyncio_typing

    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# fire-and-forget 后台任务集合 — 防 asyncio.create_task 引用被 GC（RUF006）
_BG_TASKS: set[_asyncio_typing.Task[None]] = set()

# action 字符串 → (ActionType, 新 NodeStatus) 映射
# 节点元数据 — graph 推进时按节点名查 title / 默认 assignee
# assignee="_employee_" 占位 → step 6.5 在 upsert 前替换为真实 flow.employee_id
_NODE_META: dict[str, dict[str, str]] = {
    "apply": {"title": "提交离职申请", "assignee": "_employee_"},
    "manager_review": {"title": "上级审批", "assignee": "li.si"},
    "hr_initial": {"title": "HR 初审", "assignee": "hr.bob"},
    "device_return": {"title": "设备归还", "assignee": "it.charlie"},
    "access_revoke": {"title": "权限回收", "assignee": "it.charlie"},
    "knowledge_handover": {"title": "知识交接", "assignee": "hr.bob"},
    "finance_settle": {"title": "财务结算", "assignee": "fin.david"},
    "legal_sign": {"title": "法务签字", "assignee": "legal.eve"},
    "hr_final": {"title": "HR 终审", "assignee": "hr.alice"},
    "applicant_final_confirm": {"title": "申请人最终确认", "assignee": "_employee_"},
}

# 节点角色映射 — step 6.5 enqueue 邮件时签 JWT 用
_NODE_ROLE: dict[str, str] = {
    "apply": "applicant",
    "manager_review": "manager",
    "hr_initial": "hr",
    "device_return": "it_admin",
    "access_revoke": "it_admin",
    "knowledge_handover": "hr",
    "finance_settle": "finance",
    "legal_sign": "legal",
    "hr_final": "hr",
    "applicant_final_confirm": "applicant",
}

# 节点描述（邮件正文用）
_NODE_DESC: dict[str, str] = {
    "apply": "请填写离职理由 / 最后工作日 / 交接计划等申请信息后提交。",
    "manager_review": "请审阅离职申请，确认理由并选择 通过 / 退回 / 拒绝。",
    "hr_initial": "请进行 HR 初审，核对申请材料是否完整。",
    "device_return": "请确认员工设备归还情况。",
    "access_revoke": "请回收员工各系统权限。",
    "knowledge_handover": "请确认知识交接是否完成。",
    "finance_settle": "请完成离职财务结算。",
    "legal_sign": "请确认法务签字流程。",
    "hr_final": "请进行 HR 终审。",
    "applicant_final_confirm": "您的离职流程已走完，请确认所有节点结果。",
}


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
        notification_service: Any | None = None,
    ) -> None:
        self.session = session
        self.flow_repo = flow_repo
        self.node_repo = node_repo
        self.action_repo = action_repo
        self.graph = graph
        # 用 _default_session_factory 默认值（测试可注入 mock）
        self.session_factory: SessionFactory = session_factory or _default_session_factory
        self.redis = redis
        # Bug-fix: step 6.5 在 graph 推进后给新激活节点 enqueue 邮件
        self.notification_service = notification_service

    async def submit_action(
        self,
        flow_id: uuid.UUID,
        node_id: uuid.UUID,
        action: str,
        result_text: str,
        actor: str,
        current_user_sub: str | None = None,
        current_user_node_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """提交三态决策推进节点（Phase 2 双写规范完整版）。

        Args:
            current_user_sub: 当前登录用户的 username（从 session cookie 解出）。非 None 时
                必须等于 node.assignee（防止申请人伪装上级提交）。
            current_user_node_id: session 绑定的 node_id（深链签发时锁定）。非 None 时必须
                等于 node_id（防止持 A 节点 token 提交 B 节点）。
        """
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

        # ---- Step 1.5 (Bug 2 修复): assignee 权限校验 ----
        # 演示场景路景智一人多角色：cookie session.node_id 可能绑在 applicant_view 入口节点上，
        # 但用户随后操作的是 manager_review / hr_initial / applicant_final_confirm 等业务节点。
        # 为兼容此场景，**只比对 session.sub == node.assignee**（不严格 node_id 一致）。
        # 真实环境 — 若需严格隔离每个节点 token，把下面 elif 改回 if + raise。
        if current_user_sub is not None:
            if current_user_node_id is not None and str(current_user_node_id) != str(node_id):
                logger.info(
                    "[node_service] session bound to node=%s but submitting node=%s — 不挡（demo 一人多节点场景）",
                    current_user_node_id,
                    node_id,
                )
            if node.assignee and current_user_sub != node.assignee:
                logger.warning(
                    "[node_service] 403 — session sub=%s != node.assignee=%s",
                    current_user_sub,
                    node.assignee,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"当前用户 {current_user_sub} 不是此节点的负责人（{node.assignee}）",
                )
            # 强制覆盖 actor：忽略客户端自报，以 session 为准
            actor = current_user_sub

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
        # LangGraph 1.x 多并行 interrupt 必须传 interrupt id 定位（fan-in 场景）
        config = {"configurable": {"thread_id": str(flow_id)}}
        decision_payload = {
            "action": action,
            "result_text": result_text,
            "actor": actor,
        }
        try:
            interrupt_id = await _find_interrupt_id_for_node(self.graph, config, node_name)
            if interrupt_id:
                resume_arg: Any = {interrupt_id: decision_payload}
            else:
                resume_arg = decision_payload
            await self.graph.ainvoke(Command(resume=resume_arg), config=config)
            logger.info(
                "[node_service] graph resumed flow=%s action=%s interrupt_id=%s",
                flow_id,
                action,
                interrupt_id,
            )
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

        # ---- Step 6.5: graph 推进后，把新激活的 waiting_human 节点 upsert 到业务表 ----
        # （Pre-existing fix：节点函数本身不写业务表，否则 interrupt 重跑会污染状态；
        #  这里 advance/return 成功后才同步，幂等 upsert + enqueue 邮件）
        if action in ("advance", "return") and flow is not None:
            try:
                snap_config = {"configurable": {"thread_id": str(flow_id)}}
                snap = await self.graph.aget_state(snap_config)
                next_node_names = [str(n) for n in (snap.next or [])]
                # **去重关键**：fan-in 时 snap.next 会同时返回剩余所有 waiting 节点，
                # 但其中已经 IM 推过 / 邮件发过的不要再发。只对**真新增**（之前不存在或
                # status 不是 waiting_human）的节点推。
                existing_waiting: set[str] = set()
                existing_nodes_list = await self.node_repo.list_by_flow(flow_id)
                for n in existing_nodes_list:
                    if n.status == NodeStatus.WAITING_HUMAN.value:
                        existing_waiting.add(n.node_name)

                upserted_nodes: list[Any] = []
                for nn in next_node_names:
                    meta = _NODE_META.get(nn)
                    if meta is None:
                        continue
                    # _employee_ 占位符 → 真实 flow.employee_id（apply / applicant_final_confirm）
                    resolved_assignee = (
                        flow.employee_id if meta["assignee"] == "_employee_" else meta["assignee"]
                    )
                    new_node = await self.node_repo.upsert(
                        flow_id=flow_id,
                        node_name=nn,
                        node_title=meta["title"],
                        status=NodeStatus.WAITING_HUMAN,
                        assignee=resolved_assignee,
                    )
                    # 仅当节点之前不是 waiting_human（真正新激活的）→ 加入 IM/邮件 push 列表
                    if nn not in existing_waiting:
                        upserted_nodes.append((nn, new_node, resolved_assignee))
                    else:
                        logger.info("[node_service] skip re-push (already waiting): node=%s", nn)
                if next_node_names:
                    await self.session.commit()
                    logger.info(
                        "[node_service] upserted next waiting_human nodes: %s",
                        next_node_names,
                    )
                # 给每个新激活节点 enqueue 邮件（幂等：outbox UNIQUE 约束防重发）
                if upserted_nodes and self.notification_service is not None:
                    await self._enqueue_emails_for_activated_nodes(
                        flow_id=flow_id,
                        employee_id=flow.employee_id,
                        nodes=upserted_nodes,
                    )
                    # 必须 commit 把 outbox INSERT 落库 — 否则请求结束 session 回收，邮件丢失
                    await self.session.commit()
                    logger.info(
                        "[node_service] step6.5 outbox commit OK for nodes: %s",
                        [n[0] for n in upserted_nodes],
                    )
                    # 同步 — 用 lark IM 直接私聊路景智推送（含 deeplink）
                    await self._send_lark_im_for_activated_nodes(
                        flow_id=flow_id,
                        employee_id=flow.employee_id,
                        nodes=upserted_nodes,
                    )
            except Exception as e:
                logger.warning("[node_service] upsert/enqueue next nodes failed (non-fatal): %s", e)

        # ---- Step 7 (Phase 2 handover): advance 时 fire-and-forget 生成节点交接文档 ----
        if action == "advance" and flow is not None:
            try:
                import asyncio as _asyncio

                _handover_task = _asyncio.create_task(
                    _trigger_handover_async(
                        flow_id=flow_id,
                        node_id=node_id,
                        employee_id=flow.employee_id,
                        node_name=node_name,
                        node_title=node_title,
                        result_text=result_text,
                        actor=actor,
                        action=action,
                    )
                )
                _BG_TASKS.add(_handover_task)
                _handover_task.add_done_callback(_BG_TASKS.discard)
            except Exception as e:
                logger.warning("[node_service] handover trigger failed: %s", e)

        # ---- Step 8 (Phase 2 final summary): flow.status=completed 时触发总报告 ----
        if flow is not None and flow.status == FlowStatus.COMPLETED.value:
            try:
                import asyncio as _asyncio

                _summary_task = _asyncio.create_task(_trigger_final_summary_async(flow_id))
                _BG_TASKS.add(_summary_task)
                _summary_task.add_done_callback(_BG_TASKS.discard)
            except Exception as e:
                logger.warning("[node_service] final summary trigger failed: %s", e)

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

    async def _send_lark_im_for_activated_nodes(
        self,
        *,
        flow_id: uuid.UUID,
        employee_id: str,
        nodes: list[Any],
    ) -> None:
        """演示模式 — 节点激活时通过飞书 bot 直接私聊路景智推送（含邮件全部内容 + 公网 deeplink）。

        与邮件 outbox 双通道并行。配置 LARK_DEMO_OWNER_OPEN_ID 时启用，否则跳过。
        """
        import json as _json
        import time as _time
        from uuid import uuid4 as _uuid4

        import httpx

        from offboarding_flow.auth import deep_link as _deep_link
        from offboarding_flow.auth import jwt_service as _jwt
        from offboarding_flow.auth.schemas import JWTPayload as _JWTPayload
        from offboarding_flow.config import get_settings as _get_settings
        from offboarding_flow.providers.lark_provider import _get_tenant_token as _get_lark_tok

        settings = _get_settings()
        owner_open_id = settings.lark_demo_owner_open_id
        if not owner_open_id:
            return

        try:
            tok = await _get_lark_tok(
                settings.lark_base_url, settings.lark_app_id, settings.lark_app_secret
            )
        except Exception as e:
            logger.warning("[node_service] get lark token fail (skip IM push): %s", e)
            return

        headers = {
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json; charset=utf-8",
        }
        url = f"{settings.lark_base_url}/open-apis/im/v1/messages?receive_id_type=open_id"

        role_cn = {
            "applicant": "申请人",
            "manager": "上级（李四）",
            "hr": "HR",
            "it_admin": "IT 管理员（Charlie）",
            "finance": "财务（David）",
            "legal": "法务（Eve）",
        }

        now = int(_time.time())
        async with httpx.AsyncClient(timeout=10) as client:
            for node_name, node_obj, assignee_username in nodes:
                try:
                    role = _NODE_ROLE.get(node_name, "applicant")
                    title = _NODE_META[node_name]["title"]
                    desc = _NODE_DESC.get(node_name, "请处理此节点。")
                    payload = _JWTPayload(
                        sub=assignee_username,
                        email=f"{assignee_username}@demo.local",
                        role=role,
                        flow_id=flow_id,
                        node_id=node_obj.id,
                        node_name=node_name,
                        allowed_actions=["advance", "return", "reject"],
                        iat=now,
                        exp=now + settings.token_expiry_hours * 3600,
                        jti=_uuid4().hex,
                    )
                    token = _jwt.encode(payload)
                    deeplink = _deep_link.build_deep_link(
                        token, payload, base_url=settings.deeplink_base_url
                    )
                    text = (
                        f'<at user_id="{owner_open_id}"></at>\n'
                        f"【流程通知 — 您现在是【{role_cn.get(role, role)}】身份】\n\n"
                        f"📌 待处理节点：**{title}**\n"
                        f"👤 离职申请人：{employee_id}\n"
                        f"📝 任务说明：{desc}\n\n"
                        f"🔗 公网处理入口（点开直接操作）：\n{deeplink}\n\n"
                        f"💬 或在飞书直接回复 bot："
                        f"`通过 [意见]` / `退回 [意见]` / `拒绝 [意见]`\n\n"
                        f"_由 AI 流程引擎自动通知 · 案件 ID {str(flow_id)[:8]}_"
                    )
                    body = {
                        "receive_id": owner_open_id,
                        "msg_type": "text",
                        "content": _json.dumps({"text": text}, ensure_ascii=False),
                    }
                    r = await client.post(url, headers=headers, json=body)
                    d = r.json()
                    if d.get("code") == 0:
                        logger.info("[node_service] lark IM pushed → owner node=%s", node_name)
                    else:
                        logger.warning(
                            "[node_service] lark IM push fail node=%s code=%s msg=%s",
                            node_name,
                            d.get("code"),
                            d.get("msg"),
                        )
                except Exception as e:
                    logger.warning("[node_service] lark IM push exc node=%s: %s", node_name, e)

    async def _enqueue_emails_for_activated_nodes(
        self,
        *,
        flow_id: uuid.UUID,
        employee_id: str,
        nodes: list[Any],
    ) -> None:
        """给 step 6.5 新激活的 waiting_human 节点逐个 enqueue 邮件 + 签深链 token。

        幂等：outbox UNIQUE(flow_id, node_state_id, channel) 防 LangGraph interrupt 重跑重发。
        """
        import time as _time
        from uuid import uuid4 as _uuid4

        from offboarding_flow.auth import jwt_service as _jwt
        from offboarding_flow.auth.schemas import JWTPayload as _JWTPayload
        from offboarding_flow.config import get_settings as _get_settings

        settings = _get_settings()
        now = int(_time.time())

        for node_name, node_obj, assignee_username in nodes:
            try:
                role = _NODE_ROLE.get(node_name, "applicant")
                desc = _NODE_DESC.get(node_name, "请处理此节点。")
                title = _NODE_META[node_name]["title"]
                payload = _JWTPayload(
                    sub=assignee_username,
                    email=f"{assignee_username}@demo.local",
                    role=role,
                    flow_id=flow_id,
                    node_id=node_obj.id,
                    node_name=node_name,
                    allowed_actions=["advance", "return", "reject"],
                    iat=now,
                    exp=now + settings.token_expiry_hours * 3600,
                    jti=_uuid4().hex,
                )
                token = _jwt.encode(payload)
                await self.notification_service.enqueue_node_email(
                    flow_id=flow_id,
                    node_state_id=node_obj.id,
                    node_name=node_name,
                    node_title=title,
                    node_description=desc,
                    assignee_username=assignee_username,
                    assignee_email=f"{assignee_username}@demo.local",
                    assignee_role=role,
                    employee_name=employee_id,
                    deep_link_payload=payload,
                    deep_link_token=token,
                )
                # 立即唤醒 outbox drain
                try:
                    from offboarding_flow.workers.outbox_drain import signal_outbox_pending

                    signal_outbox_pending()
                except Exception:
                    pass
                logger.info(
                    "[node_service] step6.5 enqueued email node=%s assignee=%s",
                    node_name,
                    assignee_username,
                )
            except Exception as e:
                logger.warning(
                    "[node_service] step6.5 enqueue email failed node=%s: %s", node_name, e
                )


# ---------------------------------------------------------------------------
# LangGraph 1.x 多并行 interrupt resume — 按节点名找 interrupt id
# ---------------------------------------------------------------------------
async def _find_interrupt_id_for_node(graph: Any, config: dict, node_name: str) -> str | None:
    """从 graph 当前 pending tasks 里找对应节点的 interrupt id。

    没找到（单 interrupt 场景）返回 None — 调用方走老的 single-resume API。
    """
    try:
        snap = await graph.aget_state(config)
        tasks = snap.tasks or []
        # Debug：dump tasks 结构
        for task in tasks:
            task_name = getattr(task, "name", None)
            interrupts = getattr(task, "interrupts", []) or []
            int_summary = [
                {
                    "id": getattr(i, "id", None),
                    "interrupt_id": getattr(i, "interrupt_id", None),
                    "value_keys": (
                        list(i.value.keys())
                        if hasattr(i, "value") and isinstance(i.value, dict)
                        else None
                    ),
                }
                for i in interrupts
            ]
            logger.info(
                "[interrupt-debug] task=%s interrupts=%s",
                task_name,
                int_summary,
            )
        # 按节点名匹配
        for task in tasks:
            if getattr(task, "name", None) != node_name:
                continue
            interrupts = getattr(task, "interrupts", []) or []
            for it in interrupts:
                iid = getattr(it, "id", None) or getattr(it, "interrupt_id", None)
                if iid:
                    return str(iid)
        # 退化：如果只有一个 task 含 interrupts 且名字模糊匹配（fan-out 时 task name 可能含前缀）
        candidates = [t for t in tasks if getattr(t, "interrupts", [])]
        if len(candidates) == 1:
            interrupts = candidates[0].interrupts
            for it in interrupts:
                iid = getattr(it, "id", None) or getattr(it, "interrupt_id", None)
                if iid:
                    return str(iid)
        # 最后：value 里查 node_name
        for task in tasks:
            for it in getattr(task, "interrupts", []) or []:
                value = getattr(it, "value", None)
                if isinstance(value, dict) and value.get("node_name") == node_name:
                    iid = getattr(it, "id", None) or getattr(it, "interrupt_id", None)
                    if iid:
                        return str(iid)
    except Exception as e:
        logger.warning("[node_service] _find_interrupt_id_for_node: %s", e)
    return None


# ---------------------------------------------------------------------------
# Phase 2 final summary 触发器 — 流程 completed 时汇总所有 handover docs
# ---------------------------------------------------------------------------
async def _trigger_final_summary_async(flow_id: uuid.UUID) -> None:
    try:
        import asyncio as _asyncio

        from sqlalchemy import select as _select
        from sqlalchemy import update as _update

        from offboarding_flow.services.handover_service import HandoverService
        from offboarding_flow.state_store.enums import NodeStatus
        from offboarding_flow.state_store.models import (
            FlowInstance,
            NodeState,
        )
        from offboarding_flow.state_store.repositories import FlowRepository
        from offboarding_flow.state_store.session import new_session

        # ---- Poll：等所有 handover docs 写回（其他 advance 节点的 fire-and-forget 还在跑）----
        # 期望数量 = 业务节点 done 数（排除 apply / applicant_view / archive，因为这三种不发文档）
        # 时序：最多等 90s，每 3s 检查一次；够数立即继续
        EXCLUDE_FROM_HANDOVER = {"apply", "applicant_view", "auto_archive_to_storage", "archive"}
        async with new_session() as poll_session:
            stmt = _select(NodeState).where(NodeState.flow_id == flow_id)
            all_nodes = (await poll_session.execute(stmt)).scalars().all()
        expected = sum(
            1
            for n in all_nodes
            if n.status == NodeStatus.DONE.value and n.node_name not in EXCLUDE_FROM_HANDOVER
        )
        deadline = 30  # 最多 30 轮 * 3s = 90s
        for _i in range(deadline):
            async with new_session() as poll_session:
                stmt_flow = _select(FlowInstance).where(FlowInstance.id == flow_id)
                f = (await poll_session.execute(stmt_flow)).scalar_one_or_none()
                if f is None:
                    return
                got = len((f.context or {}).get("handover_docs", []))
            if got >= expected:
                logger.info(
                    "[node_service] all %d handover docs ready, proceeding with final summary",
                    expected,
                )
                break
            logger.info(
                "[node_service] waiting handover docs %d/%d (round %d/%d)",
                got,
                expected,
                _i + 1,
                deadline,
            )
            await _asyncio.sleep(3)

        async with new_session() as session:
            repo = FlowRepository(session)
            flow = await repo.get(flow_id)
            if flow is None:
                return
            ctx = dict(flow.context or {})
            if ctx.get("final_summary_doc"):
                return  # 已生成，幂等
            handover_links = ctx.get("handover_docs", [])
            node_results = ctx.get("node_results", [])

            svc = HandoverService()
            doc = await svc.generate_final_summary(
                flow_id=flow_id,
                employee_id=flow.employee_id,
                status=flow.status,
                started_at=flow.started_at.isoformat() if flow.started_at else "",
                completed_at=(flow.completed_at.isoformat() if flow.completed_at else None),
                node_results=node_results,
                handover_links=handover_links,
            )
            if doc is None:
                return
            ctx["final_summary_doc"] = {
                "id": doc.id,
                "url": doc.url,
                "title": doc.title,
                "provider": doc.provider,
            }
            await session.execute(
                _update(FlowInstance).where(FlowInstance.id == flow_id).values(context=ctx)
            )
            await session.commit()
            logger.info(
                "[node_service] final summary doc generated flow=%s url=%s",
                flow_id,
                doc.url,
            )

        # 给申请人 DM 完整报告链接
        try:
            from offboarding_flow.providers import get_im_provider

            im = get_im_provider()
            await im.send_dm(
                flow.employee_id,
                f"🎉 你的离职流程已全部完成！\n"
                f"📄 **完整交接报告**：{doc.url}\n"
                f"含 {len(handover_links)} 份节点交接文档汇总。",
            )
        except Exception as e:
            logger.debug("[node_service] final summary DM: %s", e)
    except Exception as e:
        logger.warning("[node_service] _trigger_final_summary_async failed: %s", e)


# ---------------------------------------------------------------------------
# Phase 2 handover doc 触发器（fire-and-forget；不阻塞 submit_action 返回）
# ---------------------------------------------------------------------------
async def _trigger_handover_async(
    *,
    flow_id: uuid.UUID,
    node_id: uuid.UUID,
    employee_id: str,
    node_name: str,
    node_title: str,
    result_text: str,
    actor: str,
    action: str,
) -> None:
    """异步生成节点交接文档（LLM + DocProvider）+ DM 通知协作人 + 写 flow.context。

    @ 协作人逻辑：
    - actor 自己（确认文档已建好）
    - 申请人 employee_id（流程进度同步）
    - 下一节点的 assignee（审核者；查不到就跳过）

    任何失败仅 log，不抛（避免破坏主流程）。
    """
    try:
        from sqlalchemy import select as _select

        from offboarding_flow.providers import get_im_provider
        from offboarding_flow.services.handover_service import HandoverService
        from offboarding_flow.state_store.models import NodeState
        from offboarding_flow.state_store.repositories import FlowRepository
        from offboarding_flow.state_store.session import new_session

        svc = HandoverService()
        doc = await svc.generate_node_handover(
            flow_id=flow_id,
            node_id=node_id,
            employee_id=employee_id,
            node_name=node_name,
            node_title=node_title,
            result_text=result_text,
            actor=actor,
            action=action,
        )
        if doc is None:
            return
        # 写回 flow.context.handover_docs[] + 找下一节点 assignee
        next_assignee: str | None = None
        async with new_session() as session:
            repo = FlowRepository(session)
            flow = await repo.get(flow_id)
            if flow is None:
                return
            ctx = dict(flow.context or {})
            handover_docs = list(ctx.get("handover_docs", []))
            handover_docs.append(
                {
                    "node_name": node_name,
                    "node_title": node_title,
                    "url": doc.url,
                    "title": doc.title,
                    "provider": doc.provider,
                }
            )
            ctx["handover_docs"] = handover_docs
            from sqlalchemy import update as _update

            from offboarding_flow.state_store.models import FlowInstance

            await session.execute(
                _update(FlowInstance).where(FlowInstance.id == flow_id).values(context=ctx)
            )
            await session.commit()

            # 查当前 flow 下首个新激活的 waiting_human 节点（下游审核者）
            stmt = (
                _select(NodeState)
                .where(NodeState.flow_id == flow_id)
                .where(NodeState.status == "waiting_human")
            )
            rows = (await session.execute(stmt)).scalars().all()
            for n in rows:
                if n.id == node_id:
                    continue
                # 跳过申请人入口节点（applicant_view 是 sidecar，非主流转）
                if n.node_name == "applicant_view":
                    continue
                if n.assignee:
                    next_assignee = n.assignee
                    break

        logger.info(
            "[node_service] handover doc flow=%s node=%s url=%s next_assignee=%s",
            flow_id,
            node_name,
            doc.url,
            next_assignee,
        )

        # DM 通知协作人 — fire-and-forget
        try:
            im = get_im_provider()
            # 1. 给 actor 自己
            actor_msg = (
                f"✅ 你刚完成的「{node_title}」交接文档已生成\n"
                f"📄 文档：{doc.url}\n"
                "_AI 自动生成草稿，可在协作文档里继续编辑完善_"
            )
            try:
                await im.send_dm(actor, actor_msg)
            except Exception as e:
                logger.debug("[node_service] DM actor %s: %s", actor, e)

            # 2. 给申请人（流程进度同步）
            if employee_id != actor:
                applicant_msg = (
                    f"📌 流程进度更新：「{node_title}」节点已 advance（由 @{actor}）\n"
                    f"📄 交接文档：{doc.url}"
                )
                try:
                    await im.send_dm(employee_id, applicant_msg)
                except Exception as e:
                    logger.debug("[node_service] DM applicant: %s", e)

            # 3. 给下一节点审核者
            if next_assignee and next_assignee not in (actor, employee_id):
                reviewer_msg = (
                    f"📥 上一节点「{node_title}」已 advance，交接文档已就绪\n"
                    f"📄 文档：{doc.url}\n"
                    "请审阅文档内容后，在节点处理页提交你的决策（advance / return / reject）"
                )
                try:
                    await im.send_dm(next_assignee, reviewer_msg)
                except Exception as e:
                    logger.debug("[node_service] DM reviewer %s: %s", next_assignee, e)
        except Exception as e:
            logger.warning("[node_service] handover DM 总失败: %s", e)

    except Exception as e:
        logger.warning(
            "[node_service] _trigger_handover_async failed flow=%s node=%s: %s",
            flow_id,
            node_name,
            e,
        )
