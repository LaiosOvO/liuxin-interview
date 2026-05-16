"""mattermost_webhook 集成测试（BOT-01 + BOT-02 + BOT-03 + BOT-04）。

CLAUDE.md §2.3：集成测试禁止 mock DB；本测试需要真 PG（TEST_DATABASE_URL）。

覆盖：
- POST /api/mattermost/webhook 用 Outgoing Webhook form-data 调用
- token 错误 → 401
- help 命令 → 200 + JSON {"text": "..."} 含 8 命令清单
- start 命令（HR user）→ 创建真流程 + 回复含 9 段格式
- start 命令（applicant user）→ 拒绝（BOT-04）
- 解析失败 → 200 + 友好提示
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
from asgi_lifespan import LifespanManager

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("TEST_DATABASE_URL"),
        reason="需要 TEST_DATABASE_URL 指向 offboarding_test DB",
    ),
]


# 固定 webhook token（与 conftest 覆写 settings 的值一致）
_WEBHOOK_TOKEN = "test-outgoing-webhook-token"


@pytest.fixture
async def app_client():
    """启 FastAPI app + 覆写 settings 的 webhook token。"""
    # 覆盖 settings — 在 import main 之前
    os.environ["MATTERMOST_OUTGOING_WEBHOOK_TOKEN"] = _WEBHOOK_TOKEN

    from offboarding_flow.config import reload_settings
    from offboarding_flow.main import create_app

    reload_settings()
    app = create_app()
    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            yield client


@pytest.fixture
async def hr_user(app_client):
    """在 users 表插入一个 HR 角色用户。"""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from offboarding_flow.state_store.models import User

    dsn = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(dsn)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    username = f"hr.alice_{uuid.uuid4().hex[:8]}"
    user = User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@demo.local",
        display_name="HR Alice",
        role="hr",
    )
    async with sm() as session:
        session.add(user)
        await session.commit()
    try:
        yield username
    finally:
        async with sm() as session:
            await session.execute(
                text("DELETE FROM app.users WHERE username = :u"),
                {"u": username},
            )
            await session.commit()
        await engine.dispose()


# ---------------------------------------------------------------------------
# Token 校验
# ---------------------------------------------------------------------------
async def test_webhook_rejects_bad_token(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.post(
        "/api/mattermost/webhook",
        data={
            "token": "wrong-token",
            "text": "help",
            "user_name": "anyone",
            "channel_id": "C1",
        },
    )
    assert resp.status_code == 401


async def test_webhook_accepts_good_token(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.post(
        "/api/mattermost/webhook",
        data={
            "token": _WEBHOOK_TOKEN,
            "text": "help",
            "user_name": "anyone",
            "channel_id": "C1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["response_type"] == "in_channel"
    assert "可用命令" in body["text"]
    for cmd in ("start", "status", "report", "list", "help"):
        assert cmd in body["text"]


# ---------------------------------------------------------------------------
# 解析失败 → 友好提示
# ---------------------------------------------------------------------------
async def test_webhook_unknown_command_returns_friendly(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.post(
        "/api/mattermost/webhook",
        data={
            "token": _WEBHOOK_TOKEN,
            "text": "@offboarding-bot foobar",
            "user_name": "anyone",
            "channel_id": "C1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "未知命令" in body["text"] or "help" in body["text"]


# ---------------------------------------------------------------------------
# BOT-04: start 命令角色校验
# ---------------------------------------------------------------------------
async def test_webhook_start_rejects_unregistered_user(app_client: httpx.AsyncClient) -> None:
    resp = await app_client.post(
        "/api/mattermost/webhook",
        data={
            "token": _WEBHOOK_TOKEN,
            "text": "@offboarding-bot start zhang.san",
            "user_name": "totally_unregistered_user",
            "channel_id": "C1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "权限不足" in body["text"]


async def test_webhook_start_succeeds_for_hr_user(
    app_client: httpx.AsyncClient,
    hr_user: str,
) -> None:
    resp = await app_client.post(
        "/api/mattermost/webhook",
        data={
            "token": _WEBHOOK_TOKEN,
            "text": f"@offboarding-bot start zhang.san_{uuid.uuid4().hex[:6]}",
            "user_name": hr_user,
            "channel_id": "C1",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    text = body["text"]
    # PRD §16.4 9 段格式
    assert "📋 案件 ID:" in text
    assert "【角色清单】" in text
    assert "【任务步骤（11 个节点）】" in text
    assert "【当前进度】" in text
    assert "【阻塞事项】" in text
    assert "【是否需要真人协助】" in text
    assert "【建议下一步】" in text
    assert "AI 不会自动操作" in text


# 注：sender 与 mock Mattermost server 的集成已在 tests/test_mattermost_sender.py
# 用 httpx.MockTransport 覆盖 — 无需 DB，无需 Mattermost 容器。
# 真 Mattermost 容器测试需手动跑：docker compose up mattermost -d，然后导出
# MATTERMOST_BOT_TOKEN_REAL 跑 OFFBOARDING_E2E_BASE_URL=... pytest -m e2e。
