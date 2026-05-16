"""notification_service: 通知业务层 — 节点 first_entry 时调 enqueue_node_email。

职责：
- enqueue_node_email: 给"节点进入 waiting_human"事件入队一条 email outbox
- render_node_email: 用 jinja2 模板渲染 HTML/text 正文（含深链按钮）

不在本服务的范围（明确 Out of scope）：
- Slice 4D: APScheduler outbox_drain — 真正的 SMTP 发送由 drain job 调度
- Slice 4B: Mattermost outbox — 另外的 channel
- 失败重试策略 — 由 drain job 决定

设计原则：
- 业务层只负责"入队"（不直接调 SMTP）→ 与节点函数事务内一致提交，符合 outbox pattern
- 渲染纯函数，可独立 unit test
- 不依赖 graph / langgraph，纯 jinja2 + payload
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, select_autoescape

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from offboarding_flow.auth.schemas import JWTPayload
    from offboarding_flow.config import Settings
    from offboarding_flow.notifications.outbox_repository import OutboxRepository
    from offboarding_flow.state_store.models import NotificationOutbox

logger = logging.getLogger(__name__)

# 模板目录 — notifications/templates/*.html
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "notifications" / "templates"


@lru_cache(maxsize=1)
def _get_jinja_env() -> Environment:
    """jinja2 Environment 单例（启动后冻结）。"""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        keep_trailing_newline=False,
    )


# 角色中文映射（防 import 循环 — 跟 email_envelope 重复但解耦）
_ROLE_CN_MAP: dict[str, str] = {
    "applicant": "申请人",
    "manager": "上级",
    "hr": "HR",
    "hr_admin": "HR 总监",
    "it_admin": "设备管理员",
    "finance": "财务",
    "legal": "法务",
    "kb_owner": "知识库负责人",
    "archivist": "档案管理员",
    "admin": "管理员",
}


def render_node_waiting_email(
    *,
    employee_name: str,
    node_title: str,
    node_description: str,
    role_cn: str,
    username: str,
    deep_link_url: str,
    flow_id: uuid.UUID,
    outline_url: str = "",
) -> tuple[str, str]:
    """渲染节点 waiting_human 提醒邮件（HTML + text 两个版本）。

    Returns:
        (html_body, text_body) — 都不含演示模式横幅（横幅由 envelope 层加）

    Phase 3 build_deep_link 产出的 URL 已含 token，本函数不感知 token 内部。
    """
    env = _get_jinja_env()
    template = env.get_template("node_waiting_email.html")
    flow_id_short = str(flow_id)[:8]
    html_body = template.render(
        employee_name=employee_name,
        node_title=node_title,
        node_description=node_description,
        role_cn=role_cn,
        username=username,
        deep_link_url=deep_link_url,
        flow_id_short=flow_id_short,
        outline_url=outline_url,
    )
    # 纯文本 fallback（不依赖 HTML 渲染的邮件客户端）
    outline_hint = (
        f"\n📝 协作文档：如需创建本节点的交接文档，请到 {outline_url} 新建后把 URL 粘到节点处理页\n"
        if outline_url
        else ""
    )
    text_body = (
        f"您好，{username}：\n\n"
        f"员工 {employee_name} 的离职流程已进入【{node_title}】环节，"
        f"需要您（角色：{role_cn}）尽快处理。\n\n"
        f"节点说明：{node_description}\n\n"
        f"立即处理：{deep_link_url}{outline_hint}\n"
        f"流程 #{flow_id_short}\n"
        f"--\n离职流程系统（自动发送）"
    )
    return html_body, text_body


class NotificationService:
    """通知业务层 — enqueue + render（不调 SMTP，由 Slice 4D drain 接力）。"""

    def __init__(
        self,
        session: "AsyncSession",
        outbox_repo: "OutboxRepository",
        settings: "Settings",
    ) -> None:
        self.session = session
        self.outbox_repo = outbox_repo
        self.settings = settings

    async def enqueue_node_email(
        self,
        *,
        flow_id: uuid.UUID,
        node_state_id: uuid.UUID,
        node_name: str,
        node_title: str,
        node_description: str,
        assignee_username: str,
        assignee_email: str,
        assignee_role: str,
        employee_name: str,
        deep_link_payload: "JWTPayload | None" = None,
        deep_link_token: str | None = None,
    ) -> "NotificationOutbox | None":
        """入队一条 email outbox 记录（节点进入 waiting_human 时调）。

        幂等：同 (flow_id, node_state_id, channel='email') 第二次调用返回 None
        （UNIQUE 约束防 LangGraph interrupt 重跑场景，REQ-NOTI-04）。

        Args:
            flow_id / node_state_id: 业务表外键
            node_name / node_title / node_description: 渲染模板用元数据
            assignee_username / assignee_email / assignee_role: 责任人信息
            employee_name: 流程主体员工显示名
            deep_link_payload / deep_link_token: 已签发的 JWT（Phase 3 deep_link 产出）
                — 若为空（如测试），payload 里只存基础信息，drain 时再补
        """
        # 渲染上下文打包进 payload — drain 时直接拿去 envelope + send
        deep_link_url = None
        if deep_link_token is not None and deep_link_payload is not None:
            from offboarding_flow.auth.deep_link import build_deep_link

            deep_link_url = build_deep_link(
                deep_link_token,
                deep_link_payload,
                base_url=self.settings.deeplink_base_url,
            )

        # 渲染 HTML + text body（含「创建协作文档」入口 — 用户可选）
        role_cn = _ROLE_CN_MAP.get(assignee_role, assignee_role)
        outline_url = getattr(self.settings, "outline_url", "")
        html_body, text_body = render_node_waiting_email(
            employee_name=employee_name,
            node_title=node_title,
            node_description=node_description,
            role_cn=role_cn,
            username=assignee_username,
            deep_link_url=deep_link_url or "",
            flow_id=flow_id,
            outline_url=outline_url,
        )

        payload: dict = {
            "node_name": node_name,
            "node_title": node_title,
            "node_description": node_description,
            "assignee_username": assignee_username,
            "assignee_role": assignee_role,
            "role_cn": role_cn,
            "employee_name": employee_name,
            "base_subject": f"离职流程 — {employee_name} — {node_title} 待处理",
            "body_html": html_body,
            "body_text": text_body,
            "deep_link_url": deep_link_url,
            "deep_link_token": deep_link_token,
        }

        row = await self.outbox_repo.enqueue(
            flow_id=flow_id,
            node_state_id=node_state_id,
            channel="email",
            recipient=assignee_email,
            payload=payload,
        )
        if row is None:
            logger.info(
                "[notification_service] enqueue skipped (already in outbox) flow=%s node=%s",
                flow_id,
                node_state_id,
            )
        else:
            logger.info(
                "[notification_service] enqueued email outbox=%s flow=%s node=%s recipient=%s",
                row.id,
                flow_id,
                node_state_id,
                assignee_email,
            )
        return row
