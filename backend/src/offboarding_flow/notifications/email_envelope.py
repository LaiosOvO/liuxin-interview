"""EmailEnvelope — 演示 / 生产模式邮件投递差异的唯一收口（PRD §7.4 + PITFALLS #10）。

设计原则：
- `recipient_real` 永远是真实 assignee 邮箱 → 写入 notifications 表（审计真相）
- `delivery_to` 是 SMTP 实际投递地址：demo 模式覆写为 DEMO_INBOX，prod 模式 == recipient_real
- `subject` 在 demo 模式自动加 `[角色中文·username]` 前缀
- `body_html` 在 demo 模式自动插入演示横幅

把 demo / prod 差异在一个函数里收口，而不是散落在 SMTP client / sender —
便于 unit test 覆盖（PITFALLS #10 的预防办法）。
"""

from __future__ import annotations

from dataclasses import dataclass

from offboarding_flow.config import Settings
from offboarding_flow.state_store.enums import Role

# 角色中文映射（PRD §7.4.1 主题前缀 `[设备管理员·it.charlie]` 用）
ROLE_CN_MAP: dict[str, str] = {
    Role.APPLICANT.value: "申请人",
    Role.MANAGER.value: "上级",
    Role.HR.value: "HR",
    Role.IT_ADMIN.value: "设备管理员",
    Role.FINANCE.value: "财务",
    Role.LEGAL.value: "法务",
    Role.KB_OWNER.value: "知识库负责人",
    Role.ARCHIVIST.value: "档案管理员",
    Role.ADMIN.value: "管理员",
}

# 演示横幅模板 — 插入到 HTML body 最顶部
# PRD §7.4.1 设计的横幅文案；用纯 HTML（不依赖 jinja）确保 envelope 层独立可测
DEMO_BANNER_TEMPLATE = (
    '<div style="background:#FFF3CD;border:1px solid #FFE082;'
    "padding:12px 16px;margin-bottom:16px;border-radius:6px;"
    'font-family:Arial,sans-serif;font-size:14px;color:#5C4400;">'
    "<strong>[演示模式]</strong> 此邮件本应发送给 "
    '<code style="background:#FFEBA0;padding:2px 6px;border-radius:3px;">'
    "{real_to}</code>"
    "<br/>当前操作角色：<strong>{role_cn}</strong>"
    "<br/>点击下方按钮将以该角色身份自动登录系统。"
    "</div>"
)


@dataclass(frozen=True)
class EmailEnvelope:
    """显式邮件信封 — demo / prod 差异在这里统一表达。

    Attributes:
        recipient_real: 真实 assignee 邮箱（审计真相，写入 notifications.recipient）
        delivery_to: 实际 SMTP 投递地址（demo 模式 = DEMO_INBOX，prod 模式 = recipient_real）
        subject: 完整主题（demo 模式已经包含 [角色·username] 前缀）
        body_html: 完整 HTML 正文（demo 模式已经包含横幅）
        body_text: 纯文本备份（fallback alternative，部分客户端不支持 HTML）
        role: 责任人角色（如 'it_admin'）
        role_cn: 角色中文（如 '设备管理员'）
        username: 责任人 username
        is_demo: 标记本封是否走演示路径（log / audit 用）
    """

    recipient_real: str
    delivery_to: str
    subject: str
    body_html: str
    body_text: str
    role: str
    role_cn: str
    username: str
    is_demo: bool


def _format_role_cn(role: str) -> str:
    """role 字符串 → 中文显示，未识别 fallback 原值。"""
    return ROLE_CN_MAP.get(role, role)


# ============================================================================
# 演示模式 username → 真实邮箱映射表
# ============================================================================
# 用户明确：演示阶段把 8 个 demo user 分散到 3 个真实邮箱里收件，方便分类查看。
#
# 主流程链路（zhang.san 起 → li.si 批 → hr.bob 终审 → zhang.san 确认）→ 邮箱 A
# 部门管理者 / IT （wang.wu / hr.alice / it.charlie）→ 邮箱 B
# 后置 + 系统（fin.david / legal.eve / admin）→ 邮箱 C
#
# 通过 .env 的 DEMO_INBOX_MAP 覆盖；默认值见 PRD §9.1.3。
DEMO_INBOX_MAP_DEFAULT: dict[str, str] = {
    # 主流程链路 → 1624456575@qq.com
    "zhang.san": "1624456575@qq.com",
    "li.si": "1624456575@qq.com",
    "hr.bob": "1624456575@qq.com",
    # 部门管理者 / IT → 1691517500@qq.com
    "wang.wu": "1691517500@qq.com",
    "hr.alice": "1691517500@qq.com",
    "it.charlie": "1691517500@qq.com",
    # 后置 + 系统 → jingzhi.lu@wayz.ai
    "fin.david": "jingzhi.lu@wayz.ai",
    "legal.eve": "jingzhi.lu@wayz.ai",
    "admin": "jingzhi.lu@wayz.ai",
}


def resolve_demo_inbox(username: str, settings: Settings) -> str:
    """演示模式查 username 对应的真实收件箱。

    优先级：
    1. settings.demo_inbox_map（dict 字段，env JSON 覆盖）
    2. 内置 DEMO_INBOX_MAP_DEFAULT
    3. settings.demo_inbox（兜底全局收件箱，与原行为一致）
    """
    custom_map = getattr(settings, "demo_inbox_map", None)
    if custom_map and isinstance(custom_map, dict) and username in custom_map:
        return str(custom_map[username])
    if username in DEMO_INBOX_MAP_DEFAULT:
        return DEMO_INBOX_MAP_DEFAULT[username]
    return settings.demo_inbox


def build_envelope(
    *,
    recipient_real: str,
    base_subject: str,
    body_html: str,
    body_text: str,
    role: str,
    username: str,
    settings: Settings,
) -> EmailEnvelope:
    """构造邮件信封 — demo / prod 差异统一在此处理。

    Args:
        recipient_real: 真实 assignee 邮箱（如 it.charlie@demo.local）
        base_subject: 基础主题（如 '离职流程 — 张三 — 设备归还待处理'）
        body_html: 基础 HTML 正文（节点详情 + 深链按钮，由模板渲染产出）
        body_text: 纯文本备份
        role: 责任人角色（Role.* 之一）
        username: 责任人 username（如 it.charlie，演示前缀用）
        settings: Settings 单例（读取 app_mode + demo_inbox）

    Returns:
        EmailEnvelope: 含 delivery_to + 完整 subject + 完整 body 的不可变对象。

    实现策略（PITFALLS #10）：
    - 单一函数收口 demo / prod 差异，便于 unit test 测两种 mode 走对路径
    - demo 模式输出全部 3 个差异点：delivery_to / subject / body
    - prod 模式输出 == 直接传入值（不修改）
    """
    role_cn = _format_role_cn(role)
    is_demo = settings.is_demo

    if is_demo:
        # 按 username 查映射表（用户明确的"邮箱映射表"），未配置时 fallback 全局 demo_inbox
        delivery_to = resolve_demo_inbox(username, settings)
        subject = f"[{role_cn}·{username}] {base_subject}"
        banner = DEMO_BANNER_TEMPLATE.format(real_to=recipient_real, role_cn=role_cn)
        final_html = banner + body_html
        # text body 也带一行提示，便于 plain-text 客户端识别演示模式
        text_banner = (
            f"[演示模式] 此邮件本应发送给 {recipient_real}（角色：{role_cn}）\n"
            "点击邮件中的按钮将以该角色身份自动登录系统。\n"
            "----------\n"
        )
        final_text = text_banner + body_text
    else:
        delivery_to = recipient_real
        subject = base_subject
        final_html = body_html
        final_text = body_text

    return EmailEnvelope(
        recipient_real=recipient_real,
        delivery_to=delivery_to,
        subject=subject,
        body_html=final_html,
        body_text=final_text,
        role=role,
        role_cn=role_cn,
        username=username,
        is_demo=is_demo,
    )
