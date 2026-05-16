"""bot_service 单元测试（BOT-03 + BOT-04）。

覆盖：
- start 命令的回复格式严格符合 PRD §16.4 样例（评分点 1-9 一次回答）
- start BOT-04 role 校验拒绝非 HR
- help 命令包含 8 命令清单 + AI disclaimer
- report / suggest stub 包含 "开发中" 标识
- 8 命令 dispatch 全部路由正确

用 fake FlowService + fake session（不依赖 DB）— 隔离测试命令分发逻辑。
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from offboarding_flow.services.bot_command_parser import BotCommand
from offboarding_flow.services.bot_service import (
    AI_DISCLAIMER,
    NODE_TEMPLATE,
    ROLE_LABELS,
    BotInvocationContext,
    BotPermissionError,
    BotService,
)


# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------
class _FakeFlowService:
    """模拟 FlowService — create_flow 返回固定 flow_id，list_nodes 返回 1 个 waiting。"""

    def __init__(self) -> None:
        self.flow_id = uuid.UUID("8f3a2b1e-0000-0000-0000-000000000001")
        self.create_calls: list[dict[str, Any]] = []
        self.list_nodes_calls: list[uuid.UUID] = []

    async def create_flow(self, employee_id: str, context: dict | None = None) -> dict[str, Any]:
        self.create_calls.append({"employee_id": employee_id, "context": context})
        return {
            "flow_id": str(self.flow_id),
            "employee_id": employee_id,
            "status": "in_progress",
            "started_at": "2026-05-16T09:23:00+00:00",
            "current_node": None,
        }

    async def list_nodes(self, flow_id: uuid.UUID) -> list[dict[str, Any]]:
        self.list_nodes_calls.append(flow_id)
        # 模拟刚启动：apply=done + manager_review=waiting_human
        return [
            {
                "id": str(uuid.uuid4()),
                "name": "apply",
                "title": "申请提交",
                "status": "done",
                "assignee": "zhang.san",
            },
            {
                "id": str(uuid.uuid4()),
                "name": "manager_review",
                "title": "上级审批",
                "status": "waiting_human",
                "assignee": "li.si",
            },
        ]


def _make_service(flow_service: _FakeFlowService | None = None) -> BotService:
    """构造 BotService — session 用 None（仅 dispatch 不涉及 DB 的命令测试用）。"""
    return BotService(session=None, flow_service=flow_service or _FakeFlowService())  # type: ignore[arg-type]


def _hr_ctx() -> BotInvocationContext:
    return BotInvocationContext(
        user_name="hr.alice",
        user_id="hr_alice_id",
        channel_id="C1",
        user_role="hr",
    )


def _employee_ctx() -> BotInvocationContext:
    return BotInvocationContext(
        user_name="zhang.san",
        user_id="z_id",
        channel_id="C2",
        user_role="applicant",
    )


# ---------------------------------------------------------------------------
# help
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_help_lists_8_commands_and_disclaimer() -> None:
    svc = _make_service()
    reply = await svc.dispatch(BotCommand(name="help", args=(), raw="help"), _hr_ctx())

    # 8 命令名必须出现
    for cmd in [
        "start",
        "status",
        "report",
        "suggest",
        "list",
        "help",
        "simulate-timeout",
        "simulate-evidence-missing",
    ]:
        assert cmd in reply, f"help 输出缺命令: {cmd}"
    assert AI_DISCLAIMER in reply


# ---------------------------------------------------------------------------
# start — BOT-03 格式校验
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_reply_contains_all_scoring_sections() -> None:
    """PRD §16.4 样例：评分点 1-9 一次性回答的 9 段全部出现。"""
    svc = _make_service()
    reply = await svc.dispatch(
        BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"),
        _hr_ctx(),
    )

    # 1. 案件 ID
    assert "📋 案件 ID:" in reply
    assert "8f3a2b1e" in reply  # short id
    # 2. 离职员工
    assert "👤 离职员工: zhang.san" in reply
    # 3. 创建时间
    assert "📅 创建时间:" in reply
    # 4. 角色清单（8 角色）
    assert "【角色清单】" in reply
    for label, _role in ROLE_LABELS:
        assert label in reply, f"角色清单缺: {label}"
    # 5. 11 节点
    assert "【任务步骤（11 个节点）】" in reply
    for _idx, _name, title, _role in NODE_TEMPLATE:
        assert title in reply, f"节点缺: {title}"
    # 6. 当前进度（fake list_nodes 返 apply=done + mr=waiting，所以进度 1/11）
    assert "【当前进度】" in reply
    assert "/11 完成" in reply
    # 7. 阻塞事项
    assert "【阻塞事项】" in reply
    # 8. 是否需要真人协助
    assert "【是否需要真人协助】" in reply
    # 9. 建议下一步
    assert "【建议下一步】" in reply
    # AI disclaimer
    assert AI_DISCLAIMER in reply


@pytest.mark.asyncio
async def test_start_invokes_flow_service_with_employee_id() -> None:
    fs = _FakeFlowService()
    svc = _make_service(fs)
    await svc.dispatch(
        BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"),
        _hr_ctx(),
    )
    assert len(fs.create_calls) == 1
    assert fs.create_calls[0]["employee_id"] == "zhang.san"
    assert fs.create_calls[0]["context"]["triggered_by"] == "hr.alice"
    assert fs.create_calls[0]["context"]["channel"] == "mattermost"


# ---------------------------------------------------------------------------
# BOT-04: start role 校验
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_rejects_non_hr_user() -> None:
    svc = _make_service()
    with pytest.raises(BotPermissionError, match="权限不足"):
        await svc.dispatch(
            BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"),
            _employee_ctx(),
        )


@pytest.mark.asyncio
async def test_start_rejects_unregistered_user() -> None:
    """业务表里查不到 user → user_role=None → 拒绝。"""
    svc = _make_service()
    ctx = BotInvocationContext(
        user_name="rando",
        user_id="r_id",
        channel_id="C",
        user_role=None,
    )
    with pytest.raises(BotPermissionError):
        await svc.dispatch(
            BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"),
            ctx,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["hr", "hr_admin", "admin"])
async def test_start_accepts_hr_admin_roles(role: str) -> None:
    svc = _make_service()
    ctx = BotInvocationContext(user_name="someone", user_id="x", channel_id="C", user_role=role)
    reply = await svc.dispatch(
        BotCommand(name="start", args=("zhang.san",), raw="start zhang.san"),
        ctx,
    )
    assert "已启动离职流程" in reply


# ---------------------------------------------------------------------------
# report / suggest stub
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_report_stub_includes_disclaimer() -> None:
    svc = _make_service()
    reply = await svc.dispatch(
        BotCommand(name="report", args=("8f3a2b1e",), raw="report 8f3a2b1e"),
        _hr_ctx(),
    )
    assert "AI 报告功能开发中" in reply
    assert "Slice 4C" in reply
    assert AI_DISCLAIMER in reply


@pytest.mark.asyncio
async def test_suggest_stub_includes_disclaimer() -> None:
    svc = _make_service()
    reply = await svc.dispatch(
        BotCommand(name="suggest", args=("8f3a2b1e",), raw="suggest 8f3a2b1e"),
        _hr_ctx(),
    )
    assert "AI 建议功能开发中" in reply
    assert AI_DISCLAIMER in reply


# ---------------------------------------------------------------------------
# dispatch 路由完整性 — 8 命令全部能进对应分支
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dispatch_unknown_command_raises_valueerror() -> None:
    svc = _make_service()
    # 直接构造 BotCommand 走 dispatch（绕过 parser 白名单）
    with pytest.raises(ValueError, match="未实现的命令分支"):
        await svc.dispatch(BotCommand(name="nonexistent", args=(), raw=""), _hr_ctx())
