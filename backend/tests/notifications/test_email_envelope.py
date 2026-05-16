"""EmailEnvelope unit tests — 演示 / 生产模式差异覆盖（REQ-NOTI-03）。

测试矩阵：
- demo 模式：delivery_to 覆写 + subject 加角色前缀 + body 加横幅
- prod 模式：delivery_to == recipient_real，subject 不变，body 不变
- 未知 role：role_cn fallback 原值（不抛异常）
- recipient_real 永远保持真值（审计真相 — PRD §7.4.1）
"""

from __future__ import annotations

import pytest

from offboarding_flow.config import Settings
from offboarding_flow.notifications.email_envelope import (
    DEMO_BANNER_TEMPLATE,
    ROLE_CN_MAP,
    build_envelope,
)


def _make_settings(*, app_mode: str = "demo", demo_inbox: str = "1624456575@qq.com") -> Settings:
    """构造 Settings 实例（不读 .env，纯字段注入）。"""
    return Settings(app_mode=app_mode, demo_inbox=demo_inbox)


@pytest.mark.unit
def test_envelope_demo_mode_overrides_delivery_to() -> None:
    """演示模式：未在映射表的 username 走全局 DEMO_INBOX fallback，recipient_real 保留审计。"""
    settings = _make_settings(app_mode="demo", demo_inbox="demo@qq.com")
    env = build_envelope(
        recipient_real="unknown.user@demo.local",
        base_subject="离职流程 — 张三 — 设备归还待处理",
        body_html="<p>原始正文</p>",
        body_text="原始正文",
        role="it_admin",
        username="unknown.user",  # 不在 DEMO_INBOX_MAP 中 → fallback
        settings=settings,
    )
    assert env.recipient_real == "unknown.user@demo.local"
    assert env.delivery_to == "demo@qq.com"
    assert env.is_demo is True


@pytest.mark.unit
def test_envelope_demo_mode_routes_via_inbox_map() -> None:
    """演示模式：已知 username 走 DEMO_INBOX_MAP_DEFAULT 路由到对应真实邮箱。

    PRD §9.1.3 用户明确：8 个 demo user 按角色分散到 3 个真实邮箱便于分类查看。
    """
    settings = _make_settings(app_mode="demo", demo_inbox="fallback@qq.com")
    # zhang.san 主流程链路 → 1624456575@qq.com
    env1 = build_envelope(
        recipient_real="zhang.san@demo.local",
        base_subject="x",
        body_html="<p>x</p>",
        body_text="x",
        role="employee",
        username="zhang.san",
        settings=settings,
    )
    assert env1.delivery_to == "1624456575@qq.com"
    # it.charlie 部门管理者 / IT → 1691517500@qq.com
    env2 = build_envelope(
        recipient_real="it.charlie@demo.local",
        base_subject="x",
        body_html="<p>x</p>",
        body_text="x",
        role="it_admin",
        username="it.charlie",
        settings=settings,
    )
    assert env2.delivery_to == "1691517500@qq.com"
    # fin.david 后置 → jingzhi.lu@wayz.ai
    env3 = build_envelope(
        recipient_real="fin.david@demo.local",
        base_subject="x",
        body_html="<p>x</p>",
        body_text="x",
        role="finance",
        username="fin.david",
        settings=settings,
    )
    assert env3.delivery_to == "jingzhi.lu@wayz.ai"


@pytest.mark.unit
def test_envelope_demo_mode_subject_prefixes_role_username() -> None:
    """演示模式主题前缀 [角色中文·username] — PRD §7.4.1。"""
    settings = _make_settings(app_mode="demo")
    env = build_envelope(
        recipient_real="hr.bob@demo.local",
        base_subject="离职流程 — 张三 — HR 终审待处理",
        body_html="<p>x</p>",
        body_text="x",
        role="hr",
        username="hr.bob",
        settings=settings,
    )
    assert env.subject == "[HR·hr.bob] 离职流程 — 张三 — HR 终审待处理"
    assert env.role_cn == "HR"


@pytest.mark.unit
def test_envelope_demo_mode_body_contains_banner() -> None:
    """演示模式正文顶部插入横幅 — 包含 [演示模式] + 真实收件人 + 角色。"""
    settings = _make_settings(app_mode="demo")
    env = build_envelope(
        recipient_real="li.si@demo.local",
        base_subject="离职流程 — 张三 — 上级审批待处理",
        body_html="<p>原始正文</p>",
        body_text="原始正文",
        role="manager",
        username="li.si",
        settings=settings,
    )
    # 横幅 HTML 关键字
    assert "[演示模式]" in env.body_html
    assert "li.si@demo.local" in env.body_html
    assert "上级" in env.body_html
    # 原始正文也必须保留
    assert "<p>原始正文</p>" in env.body_html
    # text body 也必须带横幅
    assert "[演示模式]" in env.body_text
    assert "原始正文" in env.body_text


@pytest.mark.unit
def test_envelope_prod_mode_is_passthrough() -> None:
    """生产模式：delivery_to == recipient_real，subject 不加前缀，body 无横幅。"""
    settings = _make_settings(app_mode="prod", demo_inbox="should_not_be_used@qq.com")
    env = build_envelope(
        recipient_real="real@company.com",
        base_subject="离职流程 — 张三 — 设备归还待处理",
        body_html="<p>原始正文</p>",
        body_text="原始正文",
        role="it_admin",
        username="it.charlie",
        settings=settings,
    )
    assert env.delivery_to == "real@company.com"
    assert env.recipient_real == "real@company.com"
    assert env.subject == "离职流程 — 张三 — 设备归还待处理"
    assert env.body_html == "<p>原始正文</p>"
    assert env.body_text == "原始正文"
    assert env.is_demo is False


@pytest.mark.unit
def test_envelope_unknown_role_fallback_to_raw_value() -> None:
    """未识别角色：role_cn 落回原值不抛 KeyError。"""
    settings = _make_settings(app_mode="demo")
    env = build_envelope(
        recipient_real="x@x.com",
        base_subject="主题",
        body_html="x",
        body_text="x",
        role="unknown_role_xyz",
        username="someone",
        settings=settings,
    )
    assert env.role_cn == "unknown_role_xyz"
    assert env.subject.startswith("[unknown_role_xyz·someone]")


@pytest.mark.unit
def test_envelope_role_cn_map_covers_all_known_roles() -> None:
    """所有 Role 枚举值都必须在 ROLE_CN_MAP 中（防止新增 role 漏映射）。"""
    from offboarding_flow.state_store.enums import Role

    for role_member in Role:
        assert role_member.value in ROLE_CN_MAP, f"Role.{role_member.name} 未在 ROLE_CN_MAP 中"


@pytest.mark.unit
def test_demo_banner_template_includes_required_placeholders() -> None:
    """演示横幅模板必须包含 {real_to} 和 {role_cn} 两个占位（防止模板被改坏）。"""
    assert "{real_to}" in DEMO_BANNER_TEMPLATE
    assert "{role_cn}" in DEMO_BANNER_TEMPLATE
    # 横幅必须包含醒目标识，防止演示者忽略
    assert "[演示模式]" in DEMO_BANNER_TEMPLATE
