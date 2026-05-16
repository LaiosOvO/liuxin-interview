"""NotificationService unit tests — render + enqueue 行为。

覆盖：
- render_node_waiting_email: HTML 含深链 + 节点信息 + 角色；text 是纯文本 fallback
- HTML 渲染对模板变量正确转义（XSS 防护）
- enqueue_node_email: payload 包含模板渲染所需所有字段
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.config import Settings
from offboarding_flow.services.notification_service import (
    NotificationService,
    render_node_waiting_email,
)


@pytest.mark.unit
def test_render_html_contains_deep_link_and_node_info() -> None:
    """HTML 渲染结果必须含深链按钮 + 节点 title + 员工名 + 角色。"""
    html, _text = render_node_waiting_email(
        employee_name="张三",
        node_title="设备归还",
        node_description="请确认 3 台设备归还情况。",
        role_cn="设备管理员",
        username="it.charlie",
        deep_link_url="http://192.168.2.44:3000/flow/handle?flow_id=abc&node_id=xyz&token=tok123",
        flow_id=uuid.UUID("12345678-aaaa-bbbb-cccc-1234567890ab"),
    )
    # 关键字段都在 HTML
    assert "张三" in html
    assert "设备归还" in html
    assert "设备管理员" in html
    assert "it.charlie" in html
    assert "请确认 3 台设备归还情况。" in html
    # 深链以 href 形式出现 + fallback 链接文本
    # 注意：jinja autoescape 会把 & 转成 &amp;（HTML 正确行为，浏览器解析回 &）
    assert (
        "http://192.168.2.44:3000/flow/handle?flow_id=abc&amp;node_id=xyz&amp;token=tok123" in html
    )
    # 流程 id 短 hash（前 8 位）
    assert "12345678" in html
    # 立即处理按钮文案
    assert "立即处理" in html


@pytest.mark.unit
def test_render_text_is_plain_fallback() -> None:
    """text 版本必须是纯文本（无 HTML 标签），且含核心信息。"""
    _html, text = render_node_waiting_email(
        employee_name="李四",
        node_title="HR 终审",
        node_description="审阅所有节点结果。",
        role_cn="HR",
        username="hr.bob",
        deep_link_url="http://x/?token=t",
        flow_id=uuid.uuid4(),
    )
    assert "<html" not in text.lower()
    assert "<div" not in text.lower()
    assert "李四" in text
    assert "HR 终审" in text
    assert "hr.bob" in text
    assert "http://x/?token=t" in text


@pytest.mark.unit
def test_render_escapes_html_special_chars_in_employee_name() -> None:
    """模板必须自动转义用户提供的字段防 XSS（jinja autoescape）。"""
    html, _text = render_node_waiting_email(
        employee_name='<script>alert("xss")</script>',
        node_title="测试",
        node_description="x",
        role_cn="HR",
        username="u",
        deep_link_url="http://x/",
        flow_id=uuid.uuid4(),
    )
    # raw <script> 不应出现在 HTML 中（应该被转义为 &lt;）
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_node_email_packs_payload_with_subject_and_metadata() -> None:
    """enqueue 必须把渲染所需字段（base_subject / node info / role）打包到 payload。"""
    fake_outbox = MagicMock()
    fake_outbox.enqueue = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))
    settings = Settings(
        app_mode="demo",
        deeplink_base_url="http://test.local",
    )

    service = NotificationService(
        session=MagicMock(),
        outbox_repo=fake_outbox,
        settings=settings,
    )

    flow_id = uuid.uuid4()
    node_id = uuid.uuid4()
    await service.enqueue_node_email(
        flow_id=flow_id,
        node_state_id=node_id,
        node_name="manager_review",
        node_title="上级审批",
        node_description="审阅离职申请。",
        assignee_username="li.si",
        assignee_email="li.si@demo.local",
        assignee_role="manager",
        employee_name="张三",
    )

    fake_outbox.enqueue.assert_awaited_once()
    call_kwargs = fake_outbox.enqueue.await_args.kwargs
    assert call_kwargs["flow_id"] == flow_id
    assert call_kwargs["node_state_id"] == node_id
    assert call_kwargs["channel"] == "email"
    assert call_kwargs["recipient"] == "li.si@demo.local"

    payload: dict[str, Any] = call_kwargs["payload"]
    assert payload["node_name"] == "manager_review"
    assert payload["node_title"] == "上级审批"
    assert payload["assignee_username"] == "li.si"
    assert payload["assignee_role"] == "manager"
    assert payload["employee_name"] == "张三"
    # base_subject 必须由 service 拼出来（drain 时 envelope 还会加角色前缀）
    assert "张三" in payload["base_subject"]
    assert "上级审批" in payload["base_subject"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_enqueue_returns_none_when_outbox_conflict_idempotent() -> None:
    """outbox UNIQUE 冲突时 enqueue 返回 None，service 不抛异常（REQ-NOTI-04）。"""
    fake_outbox = MagicMock()
    fake_outbox.enqueue = AsyncMock(return_value=None)  # 模拟冲突

    service = NotificationService(
        session=MagicMock(),
        outbox_repo=fake_outbox,
        settings=Settings(app_mode="demo"),
    )

    result = await service.enqueue_node_email(
        flow_id=uuid.uuid4(),
        node_state_id=uuid.uuid4(),
        node_name="n",
        node_title="t",
        node_description="d",
        assignee_username="u",
        assignee_email="e@e.com",
        assignee_role="hr",
        employee_name="emp",
    )
    assert result is None  # 静默返回，调用方决定是否 log
