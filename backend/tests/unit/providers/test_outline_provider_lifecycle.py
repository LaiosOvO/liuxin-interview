"""OutlineProvider 3 个新生命周期方法单测（ABS-03）。

覆盖：
1. delete_document → OutlineClient.delete_document 被调
2. delete_document 失败 → ProviderError 包装
3. list_documents_in_collection → 调 client 并转 DocInfo
4. delete_collection → log warning + 调 client
5. delete_collection 失败 → ProviderError 包装
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.outline import OutlineError
from offboarding_flow.providers.base import ProviderError
from offboarding_flow.providers.outline_provider import OutlineProvider


def _make_mock_client() -> MagicMock:
    """造一个 OutlineClient mock — 所有方法 AsyncMock。"""
    client = MagicMock()
    client.delete_document = AsyncMock(return_value=None)
    client.list_documents_in_collection = AsyncMock(return_value=[])
    client.delete_collection = AsyncMock(return_value=None)
    return client


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """patch get_settings 避免读 .env。"""
    fake_settings = MagicMock()
    fake_settings.outline_url = "https://outline.example.com/"
    fake_settings.outline_api_token = "fake-token"
    monkeypatch.setattr(
        "offboarding_flow.providers.outline_provider.get_settings", lambda: fake_settings
    )


@pytest.mark.asyncio
async def test_delete_document_calls_client() -> None:
    """delete_document → OutlineClient.delete_document 被 awaited 一次。"""
    client = _make_mock_client()
    provider = OutlineProvider(client=client)

    await provider.delete_document("doc-abc-123")

    client.delete_document.assert_awaited_once_with("doc-abc-123")


@pytest.mark.asyncio
async def test_delete_document_wraps_outline_error_to_provider_error() -> None:
    """delete_document 失败 → ProviderError 包装（不暴露底层 OutlineError）。"""
    client = _make_mock_client()
    client.delete_document = AsyncMock(side_effect=OutlineError("HTTP 500"))
    provider = OutlineProvider(client=client)

    with pytest.raises(ProviderError, match="outline delete_document"):
        await provider.delete_document("doc-x")


@pytest.mark.asyncio
async def test_list_documents_in_collection_returns_doc_infos() -> None:
    """list_documents_in_collection → 调 client + 转 DocInfo list。"""
    client = _make_mock_client()
    client.list_documents_in_collection = AsyncMock(
        return_value=[
            {"id": "d1", "url": "/doc/d1", "title": "节点 1 交接"},
            {"id": "d2", "url": "/doc/d2", "title": "节点 2 交接"},
        ]
    )
    provider = OutlineProvider(client=client)

    docs = await provider.list_documents_in_collection(collection_id="col-zhang-san", limit=20)

    client.list_documents_in_collection.assert_awaited_once_with(
        collection_id="col-zhang-san", limit=20
    )
    assert len(docs) == 2
    assert docs[0].id == "d1"
    assert docs[0].title == "节点 1 交接"
    assert docs[0].provider == "outline"
    assert "outline.example.com" in docs[0].url


@pytest.mark.asyncio
async def test_list_documents_in_collection_wraps_outline_error() -> None:
    """list_documents_in_collection client 失败 → ProviderError。"""
    client = _make_mock_client()
    client.list_documents_in_collection = AsyncMock(side_effect=OutlineError("HTTP 401"))
    provider = OutlineProvider(client=client)

    with pytest.raises(ProviderError, match="outline list_documents_in_collection"):
        await provider.list_documents_in_collection(collection_id="x")


@pytest.mark.asyncio
async def test_delete_collection_logs_warning_and_calls_client(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """delete_collection → 先 log warning + 再 await client.delete_collection。"""
    client = _make_mock_client()
    provider = OutlineProvider(client=client)

    import logging

    with caplog.at_level(logging.WARNING, logger="offboarding_flow.providers.outline_provider"):
        await provider.delete_collection("col-archive-2024")

    client.delete_collection.assert_awaited_once_with("col-archive-2024")
    # 必须 log warning（含 "即将删除"）
    assert any(
        "即将删除 collection" in r.message for r in caplog.records
    ), "delete_collection 必须 log warning 才执行删除"


@pytest.mark.asyncio
async def test_delete_collection_wraps_outline_error_to_provider_error() -> None:
    """delete_collection 失败 → ProviderError 包装。"""
    client = _make_mock_client()
    client.delete_collection = AsyncMock(side_effect=OutlineError("HTTP 403"))
    provider = OutlineProvider(client=client)

    with pytest.raises(ProviderError, match="outline delete_collection"):
        await provider.delete_collection("col-y")
