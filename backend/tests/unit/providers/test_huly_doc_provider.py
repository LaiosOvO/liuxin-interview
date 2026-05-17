"""HulyDocProvider 单元测试 — 用 httpx.MockTransport 拦截 sidecar HTTP。

覆盖 6 用例：
1. create_collection → POST /api/doc/create_space
2. create_document → POST /api/doc/create_doc（必须传 collection_name = space_id）
3. delete_collection → DELETE /api/doc/space?id=...
4. list_documents_in_collection → GET /api/doc/list_in_space?space_id=...
5. delete_document → DELETE /api/doc/document?id=...
6. list_collections / list_documents v1 stub 返回 []
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from offboarding_flow.providers.base import DocInfo, DocProvider, ProviderError
from offboarding_flow.providers.huly_doc_provider import HulyDocProvider


def _make_settings() -> MagicMock:
    s = MagicMock()
    s.huly_bridge_url = "http://huly-bridge:7777"
    s.huly_bridge_token = "test-token-xxx"
    s.huly_bridge_http_timeout = 5.0
    return s


def _make_provider_with_transport(handler) -> HulyDocProvider:
    settings = _make_settings()
    provider = HulyDocProvider(settings)
    transport = httpx.MockTransport(handler)

    def _patched_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=settings.huly_bridge_url,
            headers={
                "Content-Type": "application/json",
                "X-Bridge-Token": settings.huly_bridge_token,
            },
            timeout=settings.huly_bridge_http_timeout,
            transport=transport,
        )

    provider._client = _patched_client  # type: ignore[method-assign]
    return provider


# ───────── 1. create_collection ─────────


@pytest.mark.asyncio
async def test_create_collection_posts_to_create_space() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True, "data": {"space_id": "ts-new-1"}})

    provider = _make_provider_with_transport(handler)
    space_id = await provider.create_collection("离职 · zhang.san", "zhang.san")

    assert space_id == "ts-new-1"
    assert captured["url"].endswith("/api/doc/create_space")
    body = json.loads(captured["body"])
    assert body == {"name": "离职 · zhang.san", "owner_username": "zhang.san"}


# ───────── 2. create_document ─────────


@pytest.mark.asyncio
async def test_create_document_posts_to_create_doc() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "doc_id": "doc-1",
                    "url": "http://huly/laios/document/doc-1",
                    "title": "工作交接",
                },
            },
        )

    provider = _make_provider_with_transport(handler)
    result = await provider.create_document(
        title="工作交接",
        markdown="# 内容",
        collection_name="ts-new-1",
    )

    assert isinstance(result, DocInfo)
    assert result.id == "doc-1"
    assert result.title == "工作交接"
    assert result.provider == "huly"
    assert captured["url"].endswith("/api/doc/create_doc")
    body = json.loads(captured["body"])
    assert body["space_id"] == "ts-new-1"


@pytest.mark.asyncio
async def test_create_document_without_collection_raises() -> None:
    provider = HulyDocProvider(_make_settings())
    with pytest.raises(ProviderError, match="collection_name"):
        await provider.create_document(title="t", markdown="m")


# ───────── 3. delete_collection ─────────


@pytest.mark.asyncio
async def test_delete_collection_deletes_space_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(
            200, json={"ok": True, "data": {"deleted": True, "documents_removed": 3}}
        )

    provider = _make_provider_with_transport(handler)
    await provider.delete_collection("ts-1")

    assert captured["method"] == "DELETE"
    assert "/api/doc/space" in captured["url"]
    assert "id=ts-1" in captured["url"]


# ───────── 4. list_documents_in_collection ─────────


@pytest.mark.asyncio
async def test_list_documents_in_collection_gets_list_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "ok": True,
                "data": {
                    "docs": [
                        {"id": "doc-1", "title": "交接 1", "url": "http://x/doc-1"},
                        {"id": "doc-2", "title": "交接 2", "url": "http://x/doc-2"},
                    ]
                },
            },
        )

    provider = _make_provider_with_transport(handler)
    docs = await provider.list_documents_in_collection(collection_id="ts-1")

    assert captured["method"] == "GET"
    assert "space_id=ts-1" in captured["url"]
    assert len(docs) == 2
    assert all(isinstance(d, DocInfo) for d in docs)
    assert docs[0].id == "doc-1"
    assert docs[1].title == "交接 2"


# ───────── 5. delete_document ─────────


@pytest.mark.asyncio
async def test_delete_document_deletes_document_endpoint() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"ok": True, "data": {"deleted": True}})

    provider = _make_provider_with_transport(handler)
    await provider.delete_document("doc-xx")

    assert captured["method"] == "DELETE"
    assert "/api/doc/document" in captured["url"]
    assert "id=doc-xx" in captured["url"]


# ───────── 6. list_collections / list_documents v1 stub ─────────


@pytest.mark.asyncio
async def test_list_collections_v1_returns_empty_list() -> None:
    provider = HulyDocProvider(_make_settings())
    assert await provider.list_collections() == []


@pytest.mark.asyncio
async def test_list_documents_v1_returns_empty_list() -> None:
    provider = HulyDocProvider(_make_settings())
    assert await provider.list_documents() == []


# ───────── 7. Protocol 校验 ─────────


def test_huly_doc_provider_satisfies_doc_provider_protocol() -> None:
    """HulyDocProvider 必须满足 DocProvider Protocol（runtime_checkable）。"""
    provider = HulyDocProvider(_make_settings())
    assert isinstance(provider, DocProvider)
    assert provider.name == "huly"


# ───────── 8. update_document v1 stub ─────────


@pytest.mark.asyncio
async def test_update_document_v1_raises_provider_error() -> None:
    provider = HulyDocProvider(_make_settings())
    with pytest.raises(ProviderError, match="update_document"):
        await provider.update_document(doc_id="doc-1", markdown="x")


# ───────── 9. ensure_users v1 no-op ─────────


@pytest.mark.asyncio
async def test_ensure_users_v1_returns_skipped_list() -> None:
    provider = HulyDocProvider(_make_settings())
    result = await provider.ensure_users(
        [{"username": "hr.alice", "email": "a@x", "name": "Alice", "role": "hr"}]
    )
    assert result == {"created": [], "skipped": ["hr.alice"]}


# ───────── 10. create_collection 错误响应 → ProviderError ─────────


@pytest.mark.asyncio
async def test_create_collection_user_not_found_raises_provider_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"ok": False, "error": "未找到 owner", "code": "USER_NOT_FOUND"},
        )

    provider = _make_provider_with_transport(handler)
    with pytest.raises(ProviderError, match="USER_NOT_FOUND"):
        await provider.create_collection("离职 · ghost", "ghost")
