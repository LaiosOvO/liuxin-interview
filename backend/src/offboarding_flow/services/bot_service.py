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
    CMD_MEETING_INGEST,
    CMD_MEETING_LIST,
    CMD_REPORT,
    CMD_SIMULATE_EVIDENCE_MISSING,
    CMD_SIMULATE_TIMEOUT,
    CMD_START,
    CMD_STATUS,
    CMD_SUGGEST,
    CMD_USERS_SYNC,
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


def _infer_role_from_username(username: str) -> str:
    """按 demo username 约定推断 role（hr.* → hr, it.* → it_admin 等）。"""
    name = username.lower()
    if name.startswith("hr."):
        return "hr_admin" if "admin" in name else "hr"
    if name.startswith("it."):
        return "it_admin"
    if name.startswith("fin."):
        return "finance"
    if name.startswith("legal."):
        return "legal"
    if name in ("admin", "root"):
        return "admin"
    # manager 不好从名字推断，给 default applicant；用户后续可手动改
    # 但 li.si / wang.wu 在演示里是 manager
    if name in ("li.si", "wang.wu", "manager"):
        return "manager"
    return "applicant"


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
    mm_helpers: 可选 {'post_channel': async fn, 'send_dm': async fn} — listener 注入
    """

    user_name: str
    user_id: str
    channel_id: str
    user_role: str | None = None
    mm_helpers: dict | None = None  # post_channel(channel_id, msg) + send_dm(username, msg)


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
            # 自然语言"我要离职"由 parser 标记 SELF_APPLY_SENTINEL → 用调用者自己当 employee
            from offboarding_flow.services.bot_command_parser import SELF_APPLY_SENTINEL

            target = ctx.user_name if cmd.args[0] == SELF_APPLY_SENTINEL else cmd.args[0]
            return await self.handle_start(target, ctx)
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
        if cmd.name == CMD_MEETING_INGEST:
            return await self.handle_meeting_ingest(cmd.args[0], ctx)
        if cmd.name == CMD_MEETING_LIST:
            return await self.handle_meeting_list(ctx)
        if cmd.name == CMD_USERS_SYNC:
            return await self.handle_users_sync(ctx)
        # 不应到达 — bot_command_parser 已穷举
        raise ValueError(f"未实现的命令分支: {cmd.name}")

    # ------------------------------------------------------------------ #
    # meeting-ingest — AI 提取会议纪要 → Outline 文档 → channel + DM 分发
    # ------------------------------------------------------------------ #
    async def handle_meeting_ingest(
        self,
        raw_text: str,
        ctx: "BotInvocationContext",
    ) -> str:
        """会议纪要 → AI 逐项分析 → Outline 创建文档 → channel post + 各 owner DM。

        说明：dispatch 时如果走 WebSocket listener，DM 真发由 listener 注入的
        mm_post_channel / mm_send_dm 回调完成；这里只返回 channel 立即回显的总结。
        """
        from offboarding_flow.services.meeting_service import MeetingService

        try:
            svc = MeetingService()
            logger.info("[bot] meeting-ingest by=%s len=%d", ctx.user_name, len(raw_text))
            extract = await svc.extract(raw_text)
            analyzed = await svc.analyze(extract)
        except Exception as e:
            logger.exception("[bot] meeting analyze 失败: %s", e)
            return (
                "⚠️ 会议纪要分析失败 — 可能 GLM 暂时不可用，请稍后重试或检查纪要格式。\n"
                f"错误：{e}"
            )

        # distribute（外部把 self._mm_helpers 注入到 ctx.extras 里时使用；
        # 这里给一个降级路径 — 不真分发，只返回 channel 摘要）
        mm_helpers = ctx.mm_helpers
        doc_url: str | None = None
        owners_notified: list[str] = []
        if mm_helpers is not None:
            try:
                result = await svc.distribute(
                    analyzed,
                    ingested_by=ctx.user_name,
                    channel_id=ctx.channel_id,
                    mm_post_channel=mm_helpers["post_channel"],
                    mm_send_dm=mm_helpers["send_dm"],
                    mm_ensure_in_channel=mm_helpers.get("ensure_in_channel"),
                )
                doc_url = result.get("doc_url")
                owners_notified = result.get("owners_notified", [])
            except Exception as e:
                logger.warning("[bot] distribute failed: %s", e)

        # 给原 channel 回一条简短回执（distribute 已经 post 了完整 announce）
        n_t = len(analyzed.tasks)
        n_b = len(analyzed.blockers)
        n_d = len(analyzed.decisions)
        msg = [f"✅ 会议「**{extract.title}**」已分析完成"]
        msg.append(f"- 任务 {n_t} 条 · 卡点 {n_b} 条 · 决策 {n_d} 条")
        if doc_url:
            msg.append(f"- 📄 协作文档：{doc_url}")
        if owners_notified:
            msg.append(f"- ✉️ 已 DM 通知：{', '.join('@'+o for o in owners_notified)}")
        if mm_helpers is None:
            msg.append("- ⚠️ (mm_helpers 未注入 — 仅返回摘要不分发)")
        msg.append("")
        msg.append(AI_DISCLAIMER)
        return "\n".join(msg)

    async def handle_users_sync(self, ctx: "BotInvocationContext") -> str:
        """同步流程：MM API 拉所有 team user → upsert system users 表 → invite Outline。"""
        try:
            from sqlalchemy import select

            from offboarding_flow.config import get_settings
            from offboarding_flow.outline import get_outline_client
            from offboarding_flow.state_store.models import User
            from offboarding_flow.state_store.repositories import UserRepository

            settings = get_settings()
            # 1. 从 MM 拉所有 team users
            mm_users = await self._fetch_mm_team_users(settings)
            # 2. upsert 到 system users 表（按 username 推断 role；过滤 bot 和系统账号）
            repo = UserRepository(self.session)
            import re as _re

            EMAIL_RE = _re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
            for mu in mm_users:
                username = mu.get("username")
                if not username:
                    continue
                # 跳过 bot 自身和明显系统账号
                if mu.get("is_bot") or username in (
                    settings.mattermost_bot_username,
                    "system",
                    "admin",
                ):
                    continue
                raw_email = (mu.get("email") or "").strip()
                # 无效或占位 email 用 demo 域兜底（让 Outline 验证通过）
                email = raw_email if EMAIL_RE.match(raw_email) else f"{username}@demo.local"
                role = _infer_role_from_username(username)
                await repo.upsert(
                    username=username,
                    email=email,
                    role=role,
                    display_name=mu.get("nickname") or username,
                )
            await self.session.commit()

            # 3. 重新读 system users → invite 到 Outline
            users = (await self.session.execute(select(User))).scalars().all()
            payloads = [
                {
                    "username": u.username,
                    "email": u.email,
                    "name": u.display_name or u.username,
                    "role": "admin" if u.role in ("hr_admin", "admin") else "member",
                }
                for u in users
            ]
            client = get_outline_client()
            result = await client.ensure_users(payloads)
            return (
                f"✅ 三层账号同步完成（MM → system → Outline）\n"
                f"- MM 拉取：{len(mm_users)} 用户\n"
                f"- system users 表：{len(users)} 用户\n"
                f"- Outline 新建：{len(result['created'])}（{', '.join(result['created']) or '无'}）\n"
                f"- Outline 已存在 skip：{len(result['skipped'])}（{', '.join(result['skipped']) or '无'}）"
            )
        except Exception as e:
            logger.exception("[bot] users-sync error: %s", e)
            return f"⚠️ 同步失败：{e}"

    async def _fetch_mm_team_users(self, settings: Any) -> list[dict[str, Any]]:
        """从 MM API 拉所有 team users（用 bot token）。"""
        import httpx

        # 先拿 team_id
        async with httpx.AsyncClient(
            base_url=settings.mattermost_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.mattermost_bot_token}"},
            timeout=10,
        ) as c:
            tr = await c.get(f"/api/v4/teams/name/{settings.mattermost_team}")
            tr.raise_for_status()
            team_id = tr.json()["id"]
            ur = await c.get("/api/v4/users", params={"in_team": team_id, "per_page": 100})
            ur.raise_for_status()
            return ur.json()

    async def handle_meeting_list(self, ctx: "BotInvocationContext") -> str:
        """列出 Outline 里"会议纪要"collection 下的最近文档。"""
        try:
            from offboarding_flow.outline import get_outline_client

            client = get_outline_client()
            cols = await client.list_collections(limit=20)
            meet_col = next((c for c in cols if c.get("name", "").startswith("会议纪要")), None)
            if not meet_col:
                return "📭 尚无任何会议文档（先用 `meeting-ingest` 创建）"
            # 调 Outline documents.list?collectionId=...
            import httpx

            from offboarding_flow.config import get_settings

            settings = get_settings()
            async with httpx.AsyncClient(
                base_url=settings.outline_url.rstrip("/") + "/api",
                headers={"Authorization": f"Bearer {settings.outline_api_token}"},
                timeout=10,
            ) as c:
                resp = await c.post(
                    "/documents.list",
                    json={"collectionId": meet_col["id"], "limit": 10, "sort": "updatedAt"},
                )
            docs = resp.json().get("data", [])
            if not docs:
                return f"📭 collection「{meet_col['name']}」为空"
            lines = [f"## 📚 最近 {len(docs)} 篇会议文档"]
            for d in docs:
                url = settings.outline_url.rstrip("/") + d.get("url", "")
                lines.append(
                    f"- [{d.get('title','(无标题)')}]({url}) · {d.get('updatedAt','')[:10]}"
                )
            return "\n".join(lines)
        except Exception as e:
            logger.warning("[bot] meeting-list error: %s", e)
            return f"⚠️ 获取会议列表失败: {e}"

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

        BOT-04: 校验 ctx.user_role ∈ {hr, hr_admin, admin}；员工给自己起流程（自助）放行。
        """
        is_self_apply = employee_username == ctx.user_name
        if not is_self_apply and ctx.user_role not in ROLES_ALLOWED_TO_START:
            raise BotPermissionError(
                f"权限不足：HR / Admin 可代他人 start；员工只能给自己 start。你的角色：{ctx.user_role or '未注册'}"
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
