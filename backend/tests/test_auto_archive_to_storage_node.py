"""test_auto_archive_to_storage_node.py — auto_archive_to_storage 节点单测（Phase 4.5）。

用 monkeypatch 替换 httpx 与 AutoNodeService — 不连真 DB / 真 mock-archive-service container。
集成 (Plan 02) 才用真 container + 真 PG。
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import httpx
import pytest

from offboarding_flow.flow_engine.nodes.auto_archive_to_storage import (
    AUTO_ARCHIVE_TO_STORAGE_NODE_NAME,
    ArchiveServiceError,
    auto_archive_to_storage_node,
)
from offboarding_flow.state_store.enums import ActionStatus


def _make_state(**overrides):
    base = {
        "flow_id": str(uuid.uuid4()),
        "employee_id": "zhang.san",
        "current_action": None,
        "node_results": [
            {
                "node_name": "manager_review",
                "node_title": "上级审批",
                "result_text": "同意",
                "actor": "li.si",
                "completed_at": "2026-05-16T10:00:00+00:00",
            },
        ],
        "context": {},
    }
    base.update(overrides)
    return base


@pytest.fixture
def patch_service_and_post(monkeypatch):
    """patch AutoNodeService 与 _post_to_archive_service，避免真 DB / 网络。"""
    from offboarding_flow.flow_engine.nodes import auto_archive_to_storage as mod

    captured: dict = {"calls": [], "post_args": []}

    async def fake_execute(**kw):
        captured["calls"].append(kw)

    fake_svc = MagicMock()
    fake_svc.execute_auto_action = fake_execute
    # 节点函数内是 delayed import — patch 模块属性
    monkeypatch.setattr(
        mod,
        "_post_to_archive_service",
        lambda *a, **kw: None,  # placeholder; tests override
    )

    # 替换 AutoNodeService 类的实例化（用 sys.modules 路径）
    import sys

    mod_svc = sys.modules.get("offboarding_flow.services.auto_node_service")
    if mod_svc:
        monkeypatch.setattr(mod_svc, "AutoNodeService", lambda: fake_svc)
    return captured


async def test_success_calls_execute_with_success_status(patch_service_and_post, monkeypatch):
    """200 OK → 调 execute_auto_action(SUCCESS) + 返回 advance。"""
    from offboarding_flow.flow_engine.nodes import auto_archive_to_storage as mod

    async def fake_post(url, body, timeout, max_retries):
        return {"archived": True, "path": "/data/archive/xx.json"}

    monkeypatch.setattr(mod, "_post_to_archive_service", fake_post)
    state = _make_state()
    result = await auto_archive_to_storage_node(state)

    assert result["current_action"] == "advance"
    assert len(result["node_results"]) == 1
    assert result["node_results"][0]["node_name"] == AUTO_ARCHIVE_TO_STORAGE_NODE_NAME
    assert result["node_results"][0]["actor"] == "system:auto"

    calls = patch_service_and_post["calls"]
    assert len(calls) == 1
    assert calls[0]["action_status"] == ActionStatus.SUCCESS
    assert calls[0]["actor"] == "system:auto"
    assert calls[0]["node_name"] == AUTO_ARCHIVE_TO_STORAGE_NODE_NAME


async def test_external_api_failure_calls_execute_with_failed_and_raises(
    patch_service_and_post, monkeypatch
):
    """httpx 抛错 → 调 execute_auto_action(FAILED) + 节点函数 raise ArchiveServiceError。"""
    from offboarding_flow.flow_engine.nodes import auto_archive_to_storage as mod

    async def fake_post_raises(url, body, timeout, max_retries):
        raise httpx.RequestError("connection refused")

    monkeypatch.setattr(mod, "_post_to_archive_service", fake_post_raises)

    with pytest.raises(ArchiveServiceError):
        await auto_archive_to_storage_node(_make_state())

    calls = patch_service_and_post["calls"]
    assert len(calls) == 1
    assert calls[0]["action_status"] == ActionStatus.FAILED
    assert "connection refused" in (calls[0].get("error_message") or "")


async def test_invalid_flow_id_raises(patch_service_and_post):
    """flow_id 非 UUID → ValueError 抛出（不调外部 API）。"""
    bad_state = _make_state(flow_id="not-a-uuid")
    with pytest.raises(ValueError):
        await auto_archive_to_storage_node(bad_state)


async def test_post_helper_retry_succeeds_on_second_attempt(monkeypatch):
    """_post_to_archive_service：第一次 RequestError，第二次成功 → 应总成功 return。"""
    from offboarding_flow.flow_engine.nodes import auto_archive_to_storage as mod

    call_count = {"n": 0}

    class FakeResponse:
        status_code = 200
        request = MagicMock()

        def raise_for_status(self):
            pass

        def json(self):
            return {"archived": True, "path": "/p"}

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, json):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise httpx.RequestError("transient")
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)

    resp = await mod._post_to_archive_service(url="http://x", body={}, timeout=1.0, max_retries=3)
    assert resp["archived"] is True
    assert call_count["n"] == 2  # 第一次失败，第二次成功


async def test_post_helper_5xx_triggers_retry_then_fail(monkeypatch):
    """_post_to_archive_service：连续 5xx → 重试 max_retries 次后抛 HTTPStatusError。"""
    from offboarding_flow.flow_engine.nodes import auto_archive_to_storage as mod

    call_count = {"n": 0}

    class FakeResponse:
        status_code = 503
        request = MagicMock()

        def raise_for_status(self):
            raise httpx.HTTPStatusError("503", request=self.request, response=self)

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, json):
            call_count["n"] += 1
            return FakeResponse()

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)

    with pytest.raises(httpx.HTTPStatusError):
        await mod._post_to_archive_service(url="http://x", body={}, timeout=1.0, max_retries=2)
    assert call_count["n"] == 2  # 2 次重试都失败


def test_node_is_async_function():
    import inspect

    assert inspect.iscoroutinefunction(auto_archive_to_storage_node)
