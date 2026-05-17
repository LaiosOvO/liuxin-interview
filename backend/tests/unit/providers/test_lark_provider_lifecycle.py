"""LarkDocsProvider 3 个新生命周期方法单测（ABS-03）。

覆盖：
1. delete_document → DELETE /open-apis/drive/v1/files/{doc_id}?type=docx 被调
2. delete_document 收到 not found → 视为幂等成功（不抛）
3. delete_document 其他错误 → 抛 ProviderError
4. list_documents_in_collection → GET /open-apis/drive/v1/files?folder_token=...
5. delete_collection → 先 log warning + DELETE folder
6. delete_collection 收到 not found → 幂等成功
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from offboarding_flow.providers.base import ProviderError


@pytest.fixture(autouse=True)
def _stub_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """stub get_settings 让 _LarkBase 构造成功。"""
    fake = MagicMock()
    fake.lark_base_url = "https://open.feishu.cn"
    fake.lark_app_id = "cli_demo"
    fake.lark_app_secret = "sec_demo"
    fake.lark_docs_folder_token = "folder_root_demo"
    monkeypatch.setattr("offboarding_flow.providers.lark_provider.get_settings", lambda: fake)


@pytest.fixture
def lark_provider(monkeypatch: pytest.MonkeyPatch):
    """构造 LarkDocsProvider 并把 _request 方法替换为 AsyncMock。"""
    from offboarding_flow.providers.lark_provider import LarkDocsProvider

    provider = LarkDocsProvider()
    provider._request = AsyncMock(return_value={})  # type: ignore[method-assign]
    return provider


@pytest.mark.asyncio
async def test_delete_document_calls_lark_drive_api(lark_provider) -> None:
    """delete_document 调 DELETE /open-apis/drive/v1/files/{doc_id}?type=docx。"""
    await lark_provider.delete_document("docx_abc123")

    lark_provider._request.assert_awaited_once_with(
        "DELETE",
        "/open-apis/drive/v1/files/docx_abc123",
        params={"type": "docx"},
    )


@pytest.mark.asyncio
async def test_delete_document_treats_not_found_as_idempotent(lark_provider) -> None:
    """delete_document 收到 not found → 视为幂等成功（不抛）。"""
    lark_provider._request = AsyncMock(side_effect=ProviderError("lark / 99991663 not found"))

    # 不抛 → 测试通过
    await lark_provider.delete_document("docx_already_gone")


@pytest.mark.asyncio
async def test_delete_document_reraises_other_errors(lark_provider) -> None:
    """delete_document 收到其他错误（403 / 500） → 重抛 ProviderError。"""
    lark_provider._request = AsyncMock(side_effect=ProviderError("lark HTTP 403 permission"))

    with pytest.raises(ProviderError, match="403"):
        await lark_provider.delete_document("docx_no_permission")


@pytest.mark.asyncio
async def test_list_documents_in_collection_returns_docx_files(lark_provider) -> None:
    """list_documents_in_collection 调 drive API 并只返 docx 类型文件。"""
    lark_provider._request = AsyncMock(
        return_value={
            "files": [
                {
                    "token": "d1",
                    "url": "https://feishu.cn/docx/d1",
                    "name": "节点 1",
                    "type": "docx",
                },
                {
                    "token": "d2",
                    "url": "https://feishu.cn/docx/d2",
                    "name": "节点 2",
                    "type": "docx",
                },
                {
                    "token": "s1",
                    "url": "https://feishu.cn/sheets/s1",
                    "name": "表格",
                    "type": "sheet",
                },
            ]
        }
    )

    docs = await lark_provider.list_documents_in_collection(
        collection_id="folder_zhang_san", limit=20
    )

    lark_provider._request.assert_awaited_once()
    call_args = lark_provider._request.call_args
    assert call_args[0] == ("GET", "/open-apis/drive/v1/files")
    assert call_args[1]["params"]["folder_token"] == "folder_zhang_san"
    assert call_args[1]["params"]["page_size"] == 20
    # 应过滤掉 sheet 类型，只留 docx
    assert len(docs) == 2
    assert all(d.provider == "lark" for d in docs)
    assert {d.id for d in docs} == {"d1", "d2"}


@pytest.mark.asyncio
async def test_list_documents_in_collection_returns_empty_on_error(
    lark_provider, caplog: pytest.LogCaptureFixture
) -> None:
    """list_documents_in_collection 报错时返回空 list + log warning（不抛）。"""
    lark_provider._request = AsyncMock(side_effect=ProviderError("HTTP 500"))

    import logging

    with caplog.at_level(logging.WARNING, logger="offboarding_flow.providers.lark_provider"):
        docs = await lark_provider.list_documents_in_collection(collection_id="x")

    assert docs == []
    assert any("list_documents_in_collection" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_delete_collection_logs_warning_and_calls_api(
    lark_provider, caplog: pytest.LogCaptureFixture
) -> None:
    """delete_collection → 先 log warning + DELETE folder。"""
    import logging

    with caplog.at_level(logging.WARNING, logger="offboarding_flow.providers.lark_provider"):
        await lark_provider.delete_collection("folder_archive_2024")

    lark_provider._request.assert_awaited_once_with(
        "DELETE",
        "/open-apis/drive/v1/files/folder_archive_2024",
        params={"type": "folder"},
    )
    assert any("即将删除 folder" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_delete_collection_treats_not_found_as_idempotent(lark_provider) -> None:
    """delete_collection 收到 not found → 幂等成功不抛。"""
    lark_provider._request = AsyncMock(side_effect=ProviderError("99991663 not found"))

    await lark_provider.delete_collection("folder_already_gone")


@pytest.mark.asyncio
async def test_delete_collection_reraises_other_errors(lark_provider) -> None:
    """delete_collection 收到其他错误 → 重抛。"""
    lark_provider._request = AsyncMock(side_effect=ProviderError("lark HTTP 500 internal"))

    with pytest.raises(ProviderError, match="500"):
        await lark_provider.delete_collection("folder_x")
