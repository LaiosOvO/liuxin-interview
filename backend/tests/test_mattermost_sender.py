"""mattermost_sender 单元测试（NOTI-02）。

用 httpx.MockTransport 拦截 HTTP 调用 — 不依赖真 Mattermost。

覆盖：
- POST /api/v4/posts 调用 URL / Header / body 正确
- attachments 嵌套到 props.attachments
- 4xx / 5xx → MattermostSendError
- httpx.RequestError 网络异常 → MattermostSendError
- build_action_attachment 字段透传
- reply_text 便捷方法
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from offboarding_flow.config import Settings
from offboarding_flow.notifications import (
    MattermostMessage,
    MattermostSender,
    MattermostSendError,
    build_action_attachment,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _settings(token: str = "test-bot-token") -> Settings:
    return Settings(
        mattermost_url="http://mm.test:8065",
        mattermost_bot_token=token,
        mattermost_http_timeout=5.0,
    )


def _client_with_handler(handler) -> httpx.AsyncClient:
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


# ---------------------------------------------------------------------------
# build_action_attachment
# ---------------------------------------------------------------------------
def test_build_action_attachment_minimal() -> None:
    att = build_action_attachment(
        title="设备归还",
        title_link=None,
        text="3 台设备待归还",
    )
    assert att["title"] == "设备归还"
    assert att["text"] == "3 台设备待归还"
    assert att["color"] == "#FFA500"
    assert "title_link" not in att
    assert "fields" not in att
    assert "actions" not in att


def test_build_action_attachment_full() -> None:
    att = build_action_attachment(
        title="设备归还",
        title_link="http://192.168.2.44:3000/flow/handle?token=xxx",
        text="请处理",
        color="#FF0000",
        fields=[{"title": "员工", "value": "张三", "short": True}],
        actions=[{"name": "继续", "integration": {"url": "/api/x"}}],
    )
    assert att["title_link"] == "http://192.168.2.44:3000/flow/handle?token=xxx"
    assert att["color"] == "#FF0000"
    assert att["fields"][0]["title"] == "员工"
    assert att["actions"][0]["name"] == "继续"


# ---------------------------------------------------------------------------
# post — URL / header / body 校验
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_post_calls_correct_url_with_bot_token() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["auth"] = request.headers.get("Authorization")
        captured["content_type"] = request.headers.get("Content-Type")
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "p1", "channel_id": "C1"})

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings("my-pat"), client=client)
    try:
        await sender.post(MattermostMessage(channel_id="C1", message="hello"))
    finally:
        await client.aclose()

    assert captured["url"] == "http://mm.test:8065/api/v4/posts"
    assert captured["method"] == "POST"
    assert captured["auth"] == "Bearer my-pat"
    assert captured["content_type"] == "application/json"
    assert captured["body"]["channel_id"] == "C1"
    assert captured["body"]["message"] == "hello"
    assert "props" not in captured["body"]  # 无 attachments 不带 props


@pytest.mark.asyncio
async def test_post_with_attachments_wraps_in_props() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "p2"})

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    try:
        att = build_action_attachment(title="t", title_link="http://x", text="d")
        await sender.post(MattermostMessage(channel_id="C1", message="m", attachments=[att]))
    finally:
        await client.aclose()

    assert "props" in captured["body"]
    assert captured["body"]["props"]["attachments"][0]["title"] == "t"


@pytest.mark.asyncio
async def test_post_4xx_raises_mattermost_send_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid token")

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    try:
        with pytest.raises(MattermostSendError) as ei:
            await sender.post(MattermostMessage(channel_id="C1", message="x"))
        assert ei.value.status_code == 401
        assert "401" in str(ei.value)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_500_raises_mattermost_send_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server boom")

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    try:
        with pytest.raises(MattermostSendError) as ei:
            await sender.post(MattermostMessage(channel_id="C1", message="x"))
        assert ei.value.status_code == 500
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_network_error_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    try:
        with pytest.raises(MattermostSendError, match="网络错误"):
            await sender.post(MattermostMessage(channel_id="C1", message="x"))
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_post_rejects_empty_channel_id() -> None:
    sender = MattermostSender(_settings())
    with pytest.raises(MattermostSendError, match="channel_id 不能为空"):
        await sender.post(MattermostMessage(channel_id="", message="x"))


@pytest.mark.asyncio
async def test_reply_text_convenience() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "p3"})

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    try:
        await sender.reply_text("C9", "hi there")
    finally:
        await client.aclose()

    assert captured["body"]["channel_id"] == "C9"
    assert captured["body"]["message"] == "hi there"


@pytest.mark.asyncio
async def test_context_manager_with_external_client_does_not_close() -> None:
    """sender 用外部传入的 client 时，__aexit__ 不应关闭它（生命周期由调用方掌握）。"""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["called"] = True
        return httpx.Response(201, json={"id": "p"})

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings(), client=client)
    async with sender as s:
        await s.post(MattermostMessage(channel_id="C1", message="x"))
    # 外部 client 必须仍存活
    assert sender._client is client
    assert captured.get("called") is True
    await client.aclose()


@pytest.mark.asyncio
async def test_full_attachment_flow_against_mock_mm_server() -> None:
    """端到端契约：sender 推一条 Interactive Message 卡片到 mock MM server。

    模拟真 Mattermost server 的 /api/v4/posts 路径 + 响应格式 — 验证 sender
    与 PRD §7.2 JSON 样板的字段对齐（attachments / fields / actions / color）。
    """
    received: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/v4/posts"
        received.append(json.loads(request.content.decode()))
        return httpx.Response(
            201,
            json={
                "id": "p_xxx",
                "create_at": 1700000000,
                "user_id": "bot_user_id",
                "channel_id": received[-1]["channel_id"],
                "message": received[-1]["message"],
            },
        )

    client = _client_with_handler(handler)
    sender = MattermostSender(_settings("real-pat"), client=client)
    try:
        att = build_action_attachment(
            title="李四 - 设备归还",
            title_link="http://192.168.2.44:3000/flow/handle?flow_id=x&node_id=y&token=z",
            text="请在 24 小时内处理 3 台设备的归还确认",
            color="#FFA500",
            fields=[
                {"title": "员工", "value": "李四（工号 12345）", "short": True},
                {"title": "节点", "value": "设备归还", "short": True},
            ],
            actions=[
                {"name": "继续", "integration": {"url": "/api/action/advance"}},
                {"name": "退回", "integration": {"url": "/api/action/return"}},
                {"name": "拒绝", "integration": {"url": "/api/action/reject"}},
            ],
        )
        result = await sender.post(
            MattermostMessage(
                channel_id="C123",
                message="您有一个待处理节点",
                attachments=[att],
            )
        )
    finally:
        await client.aclose()

    assert result["id"] == "p_xxx"
    body = received[0]
    assert body["channel_id"] == "C123"
    assert body["message"] == "您有一个待处理节点"
    assert body["props"]["attachments"][0]["title"] == "李四 - 设备归还"
    # 验证 actions 三态决策按钮全部透传
    assert len(body["props"]["attachments"][0]["actions"]) == 3
    assert body["props"]["attachments"][0]["actions"][0]["name"] == "继续"
    assert body["props"]["attachments"][0]["actions"][1]["name"] == "退回"
    assert body["props"]["attachments"][0]["actions"][2]["name"] == "拒绝"
