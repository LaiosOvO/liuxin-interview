"""Bot 服务（BOT-01..04 — PRD §16 Mattermost @bot 入口）。

8 命令 handler 分发器；每个 handler 返回纯文本回复（Mattermost 直接渲染 markdown）。

Slice 4B 范围：
- start / status / list / help / simulate-timeout / simulate-evidence-missing 真实实现
- report / suggest 返回 stub（Slice 4C 接 LLM）

约定（CLAUDE.md §5 AI 边界 + PRD §16.5 安全）：
- 所有 AI 报告输出必须带 disclaimer
- start 命令必须校验调用者 role（仅 HR / Admin）
- 命令解析交给 bot_command_parser；本服务只做业务编排

start 命令的回复严格按 PRD §16.4 样例（评分点 1-9 一次性回答）：
  案件 ID / 8 角色清单 / 11 节点状态 / 当前进度 / 阻塞 / 是否需要真人 / 建议下一步 + AI disclaimer
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import String, cast, select, update

from offboarding_flow.services.bot_command_parser import (
    CMD_HELP,
    CMD_LIST,
    CMD_REPORT,
    CMD_SIMULATE_EVIDENCE_MISSING,
    CMD_SIMULATE_TIMEOUT,
    CMD_START,
    CMD_STATUS,
    CMD_SUGGEST,
    BotCommand,
)
from offboarding_flow.state_store.enums import FlowStatus, NodeStatus
from offboarding_flow.state_store.models import FlowInstance, NodeState

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from offboarding_flow.services.flow_service import FlowService

logger = logging.getLogger(__name__)

# AI 边界 disclaimer — CLAUDE.md §5 强制（所有 AI 输出必须带）
AI_DISCLAIMER = "ℹ️ AI 不会自动操作任何节点；所有决策（继续/退回/拒绝）必须人工确认"

# 8 角色（PRD §16.4 样例 + SEED-02 — applicant 算第 8 个）
ROLE_LABELS: list[tuple[str, str]] = [
    ("离职员工", "applicant"),
    ("直属上级", "manager"),
    ("HR 专员", "hr"),
    ("HR 总监", "hr_admin"),
    ("IT 设备管理员", "it_admin"),
    ("财务专员", "finance"),
    ("法务合规", "legal"),
    ("知识库管理员", "kb_owner"),
]

# 11 节点（PRD §16.4 样例 — 10 + archive）
# tuple: (序号, 节点 name, 节点 title, 默认 assignee role)
NODE_TEMPLATE: list[tuple[int, str, str, str]] = [
    (1, "apply", "离职申请", "applicant"),
    (2, "manager_review", "上级审批", "manager"),
    (3, "hr_initial", "HR 初审", "hr"),
    (4, "device_return", "设备归还", "it_admin"),
    (5, "access_revoke", "权限回收", "it_admin"),
    (6, "knowledge_handover", "知识交接", "kb_owner"),
    (7, "finance_settle", "财务结算", "finance"),
    (8, "legal_sign", "法务签字", "legal"),
    (9, "hr_final", "HR 终审", "hr"),
    (10, "applicant_final_confirm", "申请人最终确认", "applicant"),
    (11, "archive", "归档", "hr"),
]

# 允许触发 start 命令的 role 白名单（BOT-04）
ROLES_ALLOWED_TO_START: frozenset[str] = frozenset({"hr", "hr_admin", "admin"})


# ---------------------------------------------------------------------------
# 异常 / DTO
# ---------------------------------------------------------------------------
class BotPermissionError(Exception):
    """调用者无权执行该命令（BOT-04 — 仅 HR / Admin 可 start）。"""


class BotFlowNotFoundError(Exception):
    """flow_id 在业务表里查不到 — 回复 "案件 ID 不存在"。"""


@dataclass(frozen=True)
class BotInvocationContext:
    """命令调用者上下文（Outgoing Webhook payload 解析后的精简版）。

    user_name: Mattermost 发起者 username（如 "hr.alice"）
    user_id: Mattermost user ID（备用）
    channel_id: 触发的频道 ID（回复时用）
    user_role: 业务侧 role（从 users 表查到；未注册时为 None）
    """

    user_name: str
    user_id: str
    channel_id: str
    user_role: str | None = None


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
async def _resolve_flow(session: AsyncSession, flow_id_str: str) -> FlowInstance:
    """支持完整 UUID 或 8 位短 ID（PRD §16.4 样例用 8 位）。

    8 位短 ID 的解析策略：业务表的 UUID 头 8 位 LIKE 匹配；命中多个抛错。
    """
    flow_id_str = flow_id_str.lower().strip()
    if len(flow_id_str) == 36:
        try:
            flow_id = uuid.UUID(flow_id_str)
        except ValueError as e:
            raise BotFlowNotFoundError(f"flow_id 不是合法 UUID: {flow_id_str}") from e
        flow = await session.get(FlowInstance, flow_id)
        if flow is None:
            raise BotFlowNotFoundError(f"案件 ID 不存在: {flow_id_str}")
        return flow

    # 8 位短 ID：cast(id as text) LIKE 'xxxxxxxx%'
    stmt = (
        select(FlowInstance).where(cast(FlowInstance.id, String).like(f"{flow_id_str}%")).limit(2)
    )
    result = await session.execute(stmt)
    matches = list(result.scalars().all())
    if not matches:
        raise BotFlowNotFoundError(f"案件 ID 不存在: {flow_id_str}")
    if len(matches) > 1:
        raise BotFlowNotFoundError(f"案件 ID '{flow_id_str}' 匹配多个流程，请用完整 UUID")
    return matches[0]


def _short_id(flow_id: uuid.UUID) -> str:
    return str(flow_id)[:8]


def _node_status_icon(status: str) -> str:
    """节点状态 → 图标（PRD §16.4 样例：⏳ waiting_human / ✓ done / ○ pending）。"""
    return {
        NodeStatus.WAITING_HUMAN.value: "⏳",
        NodeStatus.DONE.value: "✓",
        NodeStatus.REJECTED.value: "✗",
        NodeStatus.RETURNED.value: "↩",
        NodeStatus.IN_REVIEW.value: "⏳",
        NodeStatus.PENDING.value: "○",
    }.get(status, "○")


def _format_node_line(
    idx: int,
    title: str,
    actual_status: str | None,
    actual_assignee: str | None,
) -> str:
    """渲染单行节点状态。"""
    if actual_status is None:
        return f"{idx}. ○ {title}"
    icon = _node_status_icon(actual_status)
    extra = f"   [{actual_status}]" if actual_status != NodeStatus.PENDING.value else ""
    assignee = f"   👤 {actual_assignee}" if actual_assignee else ""
    return f"{idx}. {icon} {title}{extra}{assignee}".rstrip()


# ---------------------------------------------------------------------------
# BotService
# ---------------------------------------------------------------------------
class BotService:
    """Bot 命令编排器 — 接 FlowService / Repository / session 做实际工作。"""

    def __init__(
        self,
        session: AsyncSession,
        flow_service: FlowService,
    ) -> None:
        self.session = session
        self.flow_service = flow_service

    # ------------------------------------------------------------------ #
    # 主入口：分发
    # ------------------------------------------------------------------ #
    async def dispatch(
        self,
        cmd: BotCommand,
        ctx: BotInvocationContext,
    ) -> str:
        """根据命令名分发到对应 handler，返回回复文本。

        Raises:
            BotPermissionError: BOT-04 角色校验失败
            BotFlowNotFoundError: flow_id 查不到
            其他业务异常由 webhook 端点统一捕获
        """
        if cmd.name == CMD_HELP:
            return self.handle_help()
        if cmd.name == CMD_START:
            return await self.handle_start(cmd.args[0], ctx)
        if cmd.name == CMD_STATUS:
            return await self.handle_status(cmd.args[0])
        if cmd.name == CMD_REPORT:
            return self.handle_report_stub(cmd.args[0])
        if cmd.name == CMD_SUGGEST:
            return self.handle_suggest_stub(cmd.args[0])
        if cmd.name == CMD_LIST:
            return await self.handle_list(cmd.args[0])
        if cmd.name == CMD_SIMULATE_TIMEOUT:
            return await self.handle_simulate_timeout(cmd.args[0], cmd.args[1])
        if cmd.name == CMD_SIMULATE_EVIDENCE_MISSING:
            return await self.handle_simulate_evidence_missing(cmd.args[0], cmd.args[1])
        # 不应到达 — bot_command_parser 已穷举
        raise ValueError(f"未实现的命令分支: {cmd.name}")

    # ------------------------------------------------------------------ #
    # help
    # ------------------------------------------------------------------ #
    def handle_help(self) -> str:
        return (
            "🤖 [离职流程 Bot] 可用命令\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "• `@offboarding-bot start <username>` — 创建一个新的离职流程实例\n"
            "• `@offboarding-bot status <flow_id>` — 查询流程当前状态\n"
            "• `@offboarding-bot report <flow_id>` — 生成 AI 后台报告\n"
            "• `@offboarding-bot suggest <flow_id>` — AI 建议下一步\n"
            "• `@offboarding-bot list [active|completed|stuck]` — 列出流程实例\n"
            "• `@offboarding-bot help` — 命令帮助\n"
            "• `@offboarding-bot simulate-timeout <flow_id> <node>` — 模拟节点逾期（demo 用）\n"
            "• `@offboarding-bot simulate-evidence-missing <flow_id> <node>` — 模拟证据缺失（demo 用）\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{AI_DISCLAIMER}"
        )

    # ------------------------------------------------------------------ #
    # start
    # ------------------------------------------------------------------ #
    async def handle_start(
        self,
        employee_username: str,
        ctx: BotInvocationContext,
    ) -> str:
        """创建新流程并返回评分点 #1-9 一次性回答的格式（PRD §16.4）。

        BOT-04: 校验 ctx.user_role ∈ {hr, hr_admin, admin}；否则拒绝。
        """
        if ctx.user_role not in ROLES_ALLOWED_TO_START:
            raise BotPermissionError(
                f"权限不足：仅 HR / Admin 可触发 start 命令；你的角色：{ctx.user_role or '未注册'}"
            )

        # 1. 调用 FlowService.create_flow（复用 Phase 2 业务逻辑）
        result = await self.flow_service.create_flow(
            employee_id=employee_username,
            context={
                "triggered_by": ctx.user_name,
                "channel": "mattermost",
                "via": "bot:start",
            },
        )
        flow_id_str = result["flow_id"]
        flow_id = uuid.UUID(flow_id_str)
        short_id = _short_id(flow_id)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 2. 读最新节点状态拼回复
        nodes = await self.flow_service.list_nodes(flow_id)
        nodes_by_name = {n["name"]: n for n in nodes}
        completed_count = sum(1 for n in nodes if n["status"] == NodeStatus.DONE.value)

        # 3. 渲染各段
        lines = [
            "🤖 [AI 助手] 已启动离职流程",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📋 案件 ID: {short_id}",
            f"👤 离职员工: {employee_username}",
            f"📅 创建时间: {now}",
            "",
            "【角色清单】",
        ]
        for label, role in ROLE_LABELS:
            lines.append(f"• {label}: {role}")
        lines.append("")
        lines.append(f"【任务步骤（{len(NODE_TEMPLATE)} 个节点）】")
        for idx, node_name, title, _role in NODE_TEMPLATE:
            actual = nodes_by_name.get(node_name)
            actual_status = actual["status"] if actual else None
            actual_assignee = actual["assignee"] if actual else None
            lines.append(_format_node_line(idx, title, actual_status, actual_assignee))
        lines.append("")
        lines.append(f"【当前进度】 {completed_count}/{len(NODE_TEMPLATE)} 完成（刚启动）")
        lines.append("")
        lines.append(f"【阻塞事项】 暂无 — 等待 {employee_username} 填写离职申请")
        lines.append("")
        lines.append(f"【是否需要真人协助】 是 — {employee_username} 需要先填写离职申请表")
        lines.append("")
        lines.append(f"【建议下一步】 已自动发邮件给 {employee_username} 触发离职申请填写")
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(AI_DISCLAIMER)
        lines.append(f"*Type `@offboarding-bot report {short_id}` 查看详细 AI 报告*")

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # status
    # ------------------------------------------------------------------ #
    async def handle_status(self, flow_id_str: str) -> str:
        flow = await _resolve_flow(self.session, flow_id_str)
        nodes = await self.flow_service.list_nodes(flow.id)
        completed = sum(1 for n in nodes if n["status"] == NodeStatus.DONE.value)
        current = next(
            (n for n in nodes if n["status"] == NodeStatus.WAITING_HUMAN.value),
            None,
        )

        lines = [
            f"📋 案件 ID: {_short_id(flow.id)}",
            f"👤 员工: {flow.employee_id}",
            f"📊 状态: {flow.status}",
            f"📈 进度: {completed}/{len(nodes)} 完成",
        ]
        if current:
            lines.append(
                f"⏳ 当前节点: {current['title']}（{current['name']}）→ {current['assignee'] or '未分配'}"
            )
        else:
            lines.append("⏳ 当前节点: 无活跃 waiting_human 节点")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # report / suggest — Slice 4C 接 LLM；Slice 4B 先 stub
    # ------------------------------------------------------------------ #
    def handle_report_stub(self, flow_id_str: str) -> str:
        return (
            f"🤖 [AI 报告] 案件 {flow_id_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "AI 报告功能开发中（Slice 4C 接 LLM）— 当前可用 `status` 查看结构化状态。\n"
            f"{AI_DISCLAIMER}"
        )

    def handle_suggest_stub(self, flow_id_str: str) -> str:
        return (
            f"🤖 [AI 建议] 案件 {flow_id_str}\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "AI 建议功能开发中（Slice 4C 接 LLM）— 当前可用 `status` 查看结构化状态。\n"
            f"{AI_DISCLAIMER}"
        )

    # ------------------------------------------------------------------ #
    # list
    # ------------------------------------------------------------------ #
    async def handle_list(self, filter_name: str) -> str:
        # filter 决定 status 查询条件
        status_filter: list[str] = {
            "active": [FlowStatus.IN_PROGRESS.value],
            "completed": [FlowStatus.COMPLETED.value],
            # stuck = 有 waiting_human 节点 is_overdue=True 的 in_progress 流程
            "stuck": [FlowStatus.IN_PROGRESS.value],
        }.get(filter_name, [FlowStatus.IN_PROGRESS.value])

        stmt = (
            select(FlowInstance)
            .where(FlowInstance.status.in_(status_filter))
            .order_by(FlowInstance.started_at.desc())
            .limit(20)
        )
        result = await self.session.execute(stmt)
        flows = list(result.scalars().all())

        if filter_name == "stuck":
            # 二次过滤：必须存在 is_overdue=True 节点
            overdue_stmt = (
                select(NodeState.flow_id).where(NodeState.is_overdue.is_(True)).distinct()
            )
            overdue_ids = {
                row for row in (await self.session.execute(overdue_stmt)).scalars().all()
            }
            flows = [f for f in flows if f.id in overdue_ids]

        if not flows:
            return f"📋 [list {filter_name}] 暂无流程"

        lines = [f"📋 [list {filter_name}] 共 {len(flows)} 个流程", ""]
        for f in flows:
            started = f.started_at.strftime("%Y-%m-%d %H:%M") if f.started_at else "?"
            lines.append(f"• {_short_id(f.id)} — {f.employee_id} — {f.status} — 启动于 {started}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # simulate-timeout
    # ------------------------------------------------------------------ #
    async def handle_simulate_timeout(self, flow_id_str: str, node_name: str) -> str:
        """立即标记节点 is_overdue=True（PRD §17.1 demo 用）。"""
        flow = await _resolve_flow(self.session, flow_id_str)
        stmt = (
            update(NodeState)
            .where(
                NodeState.flow_id == flow.id,
                NodeState.node_name == node_name,
            )
            .values(is_overdue=True)
            .returning(NodeState.id)
        )
        result = await self.session.execute(stmt)
        ids = list(result.scalars().all())
        await self.session.commit()
        if not ids:
            return (
                f"⚠️ 节点 '{node_name}' 在案件 {_short_id(flow.id)} 中不存在；"
                "请用 `status <flow_id>` 查看可用节点"
            )
        return (
            f"⏰ [模拟逾期] 案件 {_short_id(flow.id)} 节点 '{node_name}' 已标记 is_overdue=True\n"
            f"{AI_DISCLAIMER}"
        )

    # ------------------------------------------------------------------ #
    # simulate-evidence-missing
    # ------------------------------------------------------------------ #
    async def handle_simulate_evidence_missing(self, flow_id_str: str, node_name: str) -> str:
        """立即标记节点证据缺失（PRD §17.2 demo 用）。

        Slice 4B 暂用 flow_instances.context.evidence_missing_nodes 数组承担
        （Slice 4A 若加 node_states.evidence_missing 列再切换）。
        """
        flow = await _resolve_flow(self.session, flow_id_str)
        # 确认节点存在
        node_stmt = select(NodeState).where(
            NodeState.flow_id == flow.id,
            NodeState.node_name == node_name,
        )
        node = (await self.session.execute(node_stmt)).scalar_one_or_none()
        if node is None:
            return (
                f"⚠️ 节点 '{node_name}' 在案件 {_short_id(flow.id)} 中不存在；"
                "请用 `status <flow_id>` 查看可用节点"
            )

        # context.evidence_missing_nodes append (immutability — 新建 dict 不改原)
        context: dict[str, Any] = dict(flow.context or {})
        missing = list(context.get("evidence_missing_nodes", []))
        if node_name not in missing:
            missing.append(node_name)
        context["evidence_missing_nodes"] = missing
        flow.context = context
        await self.session.commit()

        return (
            f"⚠️ [模拟证据缺失] 案件 {_short_id(flow.id)} 节点 '{node_name}' "
            f"已标记到 context.evidence_missing_nodes\n"
            f"{AI_DISCLAIMER}"
        )
