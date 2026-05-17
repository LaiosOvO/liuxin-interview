"""OutlineClient 新增的 3 个生命周期方法单测（ABS-03 — 底层 client 层）。

覆盖：
1. delete_document → POST /documents.delete
2. delete_document 404 → 视为幂等成功
3. delete_document 500 → 抛 OutlineError
4. list_documents_in_collection → POST /documents.list
5. delete_collection → POST /collections.delete
6. delete_collection 404 → 视为幂等成功

测试用 respx mock httpx；不真打 Outline。
"""

from __future__ import annotations

import httpx
import pytest

from offboarding_flow.outline import OutlineClient, OutlineError


@pytest.fixture
def client() -> OutlineClient:
    return OutlineClient(base_url="https://outline.test", api_token="fake-token")


@pytest.mark.asyncio
async def test_delete_document_posts_to_documents_delete(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_document → POST /documents.delete {"id": doc_id}，200 视为成功。"""
    captured: dict = {}

    class _StubResp:
        status_code = 200

        def json(self) -> dict:
            return {"ok": True}

        @property
        def text(self) -> str:
            return ""

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_StubAsyncClient":
            return self

        async def __aexit__(self, *args) -> None:
            return None

        async def post(self, path: str, json: dict | None = None) -> _StubResp:
            captured["path"] = path
            captured["json"] = json
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    await client.delete_document("doc-id-xx")

    assert captured["path"] == "/documents.delete"
    assert captured["json"] == {"id": "doc-id-xx"}


@pytest.mark.asyncio
async def test_delete_document_404_is_idempotent_success(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_document 404 → 视为幂等成功（不抛）。"""

    class _StubResp:
        status_code = 404
        text = "not found"

        def json(self) -> dict:
            return {}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    # 不抛 → 测试通过
    await client.delete_document("doc-already-gone")


@pytest.mark.asyncio
async def test_delete_document_500_raises_outline_error(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_document 500 → 抛 OutlineError。"""

    class _StubResp:
        status_code = 500
        text = "internal err"

        def json(self):
            return {}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    with pytest.raises(OutlineError, match="HTTP 500"):
        await client.delete_document("doc-x")


@pytest.mark.asyncio
async def test_delete_document_httpx_error_wrapped(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_document 网络错误（httpx.HTTPError） → OutlineError 包装。"""

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    with pytest.raises(OutlineError, match=r"documents\.delete"):
        await client.delete_document("doc-x")


@pytest.mark.asyncio
async def test_list_documents_in_collection_posts_correct_body(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """list_documents_in_collection → POST /documents.list {"collectionId":..., "limit":...}。"""
    captured: dict = {}
    docs = [{"id": "d1", "title": "节点 1"}, {"id": "d2", "title": "节点 2"}]

    class _StubResp:
        status_code = 200
        text = ""

        def json(self):
            return {"data": docs}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            captured["path"] = path
            captured["json"] = json
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    result = await client.list_documents_in_collection(collection_id="col-1", limit=20)

    assert captured["path"] == "/documents.list"
    assert captured["json"]["collectionId"] == "col-1"
    assert captured["json"]["limit"] == 20
    assert captured["json"]["sort"] == "updatedAt"
    assert result == docs


@pytest.mark.asyncio
async def test_list_documents_in_collection_caps_limit_at_100(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """limit > 100 时 Outline API 不支持 — 强制截到 100。"""
    captured: dict = {}

    class _StubResp:
        status_code = 200

        def json(self):
            return {"data": []}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            captured["json"] = json
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    await client.list_documents_in_collection(collection_id="c", limit=500)

    assert captured["json"]["limit"] == 100


@pytest.mark.asyncio
async def test_delete_collection_posts_to_collections_delete(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_collection → POST /collections.delete {"id": collection_id}。"""
    captured: dict = {}

    class _StubResp:
        status_code = 200

        def json(self):
            return {"ok": True}

        text = ""

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            captured["path"] = path
            captured["json"] = json
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    await client.delete_collection("col-x")

    assert captured["path"] == "/collections.delete"
    assert captured["json"] == {"id": "col-x"}


@pytest.mark.asyncio
async def test_delete_collection_404_is_idempotent_success(
    monkeypatch: pytest.MonkeyPatch, client: OutlineClient
) -> None:
    """delete_collection 404 → 视为幂等成功（不抛）。"""

    class _StubResp:
        status_code = 404
        text = "not found"

        def json(self):
            return {}

    class _StubAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json=None):
            return _StubResp()

    monkeypatch.setattr("offboarding_flow.outline.client.httpx.AsyncClient", _StubAsyncClient)

    await client.delete_collection("col-already-gone")
