"""Outline DocProvider — 包装现有 OutlineClient 符合 DocProvider 接口。"""

from __future__ import annotations

import logging

from offboarding_flow.config import get_settings
from offboarding_flow.outline import OutlineClient, OutlineError, get_outline_client

from .base import DocInfo, ProviderError

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "会议纪要 / Meetings"
HANDOVER_COLLECTION_NAME = "离职交接 / Offboarding"


class OutlineProvider:
    """Outline 实现的 DocProvider。"""

    name = "outline"

    def __init__(
        self,
        client: OutlineClient | None = None,
        default_collection: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        self._client = client
        self.default_collection = default_collection

    def _get_client(self) -> OutlineClient:
        if self._client is None:
            self._client = get_outline_client()
        return self._client

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owner_usernames: list[str] | None = None,
        collection_name: str | None = None,
    ) -> DocInfo:
        client = self._get_client()
        coll_name = collection_name or self.default_collection
        try:
            collection = await client.ensure_collection(coll_name)
            doc = await client.create_document(
                title=title,
                text=markdown,
                collection_id=collection["id"],
                publish=True,
            )
        except OutlineError as e:
            raise ProviderError(f"outline create_document: {e}") from e
        settings = get_settings()
        full_url = settings.outline_url.rstrip("/") + str(doc.get("url", ""))
        return DocInfo(id=doc["id"], url=full_url, title=title, provider=self.name)

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None:
        client = self._get_client()
        try:
            await client.update_document(
                document_id=doc_id, text=markdown, title=title, publish=True
            )
        except OutlineError as e:
            raise ProviderError(f"outline update_document: {e}") from e

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]:
        client = self._get_client()
        try:
            if query:
                raw = await client.search_documents(query, limit=limit)
            else:
                # list_documents 端点 — 取 collection 下所有
                col = await client.ensure_collection(self.default_collection)
                import httpx

                settings = get_settings()
                async with httpx.AsyncClient(
                    base_url=settings.outline_url.rstrip("/") + "/api",
                    headers={"Authorization": f"Bearer {settings.outline_api_token}"},
                    timeout=10,
                ) as c:
                    resp = await c.post(
                        "/documents.list",
                        json={
                            "collectionId": col["id"],
                            "limit": limit,
                            "sort": "updatedAt",
                        },
                    )
                raw = resp.json().get("data", [])
        except Exception as e:
            raise ProviderError(f"outline list_documents: {e}") from e
        settings = get_settings()
        return [
            DocInfo(
                id=d.get("id", ""),
                url=settings.outline_url.rstrip("/") + d.get("url", ""),
                title=d.get("title", ""),
                provider=self.name,
            )
            for d in raw
        ]

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        client = self._get_client()
        try:
            return await client.ensure_users(users)
        except OutlineError as e:
            raise ProviderError(f"outline ensure_users: {e}") from e

    async def get_document(self, doc_id: str) -> DocInfo | None:
        client = self._get_client()
        try:
            doc = await client.get_document(doc_id)
            settings = get_settings()
            return DocInfo(
                id=doc["id"],
                url=settings.outline_url.rstrip("/") + doc.get("url", ""),
                title=doc.get("title", ""),
                provider=self.name,
            )
        except OutlineError:
            return None

    # ------------------------------------------------------------------ #
    # ABS-03 — 完整生命周期方法（Phase 08-01 新增）
    # ------------------------------------------------------------------ #

    async def delete_document(self, doc_id: str) -> None:
        """删除单篇文档（移入 Outline 垃圾箱）。"""
        client = self._get_client()
        try:
            await client.delete_document(doc_id)
        except OutlineError as e:
            raise ProviderError(f"outline delete_document: {e}") from e

    async def list_documents_in_collection(
        self,
        *,
        collection_id: str,
        limit: int = 50,
    ) -> list[DocInfo]:
        """列出指定 collection 下的所有文档。"""
        client = self._get_client()
        try:
            raw = await client.list_documents_in_collection(
                collection_id=collection_id,
                limit=limit,
            )
        except OutlineError as e:
            raise ProviderError(f"outline list_documents_in_collection: {e}") from e
        settings = get_settings()
        return [
            DocInfo(
                id=d.get("id", ""),
                url=settings.outline_url.rstrip("/") + d.get("url", ""),
                title=d.get("title", ""),
                provider=self.name,
            )
            for d in raw
        ]

    async def delete_collection(self, collection_id: str) -> None:
        """删除整个 collection（连带下面所有文档）。

        ⚠️ 危险：Outline 服务端会移走所有文档；本方法不做二次确认，
        调用方须自己确保已通过 UI 提醒或审计 hook。
        """
        client = self._get_client()
        logger.warning("[outline-provider] 即将删除 collection %s（含所有文档）", collection_id)
        try:
            await client.delete_collection(collection_id)
        except OutlineError as e:
            raise ProviderError(f"outline delete_collection: {e}") from e
