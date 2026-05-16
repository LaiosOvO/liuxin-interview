"""E2E: 跨 flow_id 复用 token 立即拒绝。

验收 ROADMAP §Phase 3 Success Criteria #5
场景：token.flow_id=flow_a 但 URL node_id 属于 flow_b → exchange 401（cross_flow reason）
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from offboarding_flow.auth import JWTPayload, encode

pytestmark = pytest.mark.asyncio


async def test_token_for_flow_a_rejected_on_flow_b(
    http_client: httpx.AsyncClient,
    two_flows_with_nodes,
    redis_client,
) -> None:
    """token 的 flow_id=A 但 URL 携带 node 属于 flow_b → exchange 401。

    session_service 第 3 步：str(node.flow_id) != str(payload.flow_id) → AuthError(reason='cross_flow')
    """
    flow_a = two_flows_with_nodes["flow_a"]
    node_b = two_flows_with_nodes["node_b"]
    user = two_flows_with_nodes["user"]

    payload = JWTPayload(
        sub=user.username,
        email="li.si@demo.local",
        role="manager",
        flow_id=flow_a.id,  # 错的 flow_id
        node_id=node_b.id,  # node 属于 flow_b
        node_name="manager_review",
        allowed_actions=["advance"],
        iat=int(time.time()),
        exp=int(time.time()) + 3600,
        jti=uuid.uuid4().hex,
    )
    token = encode(payload)

    resp = await http_client.post("/api/auth/exchange", json={"token": token})
    assert resp.status_code == 401
