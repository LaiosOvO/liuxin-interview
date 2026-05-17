"""Huly DocProvider — Python 直连 REST 实现（Phase 8 B-full 重构，去 sidecar）。

设计：
- Teamspace (collection) 通过 ops.create_doc 创建
- Document 通过 ops.create_doc 创建（attachedTo=parent_id 或 NoParent）
- 列表/查询走 rest.find_all
- 删除走 ops.remove_doc

URL 构造规则与 sidecar 时代对齐：
    http://192.168.2.44:8087/workbench/laios/document/{doc_id}
"""

from __future__ import annotations

import asyncio
import logging
import time

from offboarding_flow.config import Settings

from .base import DocInfo, ProviderError
from .huly import (
    CORE_SPACE_SPACE,
    DOCUMENT_CLASS_DOCUMENT,
    DOCUMENT_CLASS_TEAMSPACE,
    DOCUMENT_IDS_NO_PARENT,
    DOCUMENT_TYPE_DEFAULT,
    HulyPlatformClient,
    connect_huly,
)

logger = logging.getLogger(__name__)


class HulyDocProvider:
    """Huly DocProvider — Python REST 直连，无 sidecar。"""

    name = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: HulyPlatformClient | None = None
        self._connect_lock = asyncio.Lock()

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    async def _ensure_client(self) -> HulyPlatformClient:
        if self._client is not None:
            return self._client
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            s = self._settings
            if not s.huly_admin_email or not s.huly_admin_password:
                raise ProviderError(
                    "Huly admin 凭证未配置 — 检查 HULY_ADMIN_EMAIL / HULY_ADMIN_PASSWORD"
                )
            try:
                self._client = await connect_huly(
                    accounts_url=s.huly_accounts_url,
                    admin_email=s.huly_admin_email,
                    admin_password=s.huly_admin_password,
                    workspace_url=s.huly_workspace,
                    timeout=s.huly_http_timeout,
                )
            except Exception as e:
                raise ProviderError(f"connect_huly 失败: {e}") from e
            assert self._client is not None
            return self._client

    def _build_doc_url(self, doc_id: str) -> str:
        base = self._settings.huly_url.rstrip("/")
        workspace = self._settings.huly_workspace
        return f"{base}/workbench/{workspace}/document/{doc_id}"

    # ------------------------------------------------------------------ #
    # Phase 7 老接口（保持兼容） — create / update / list / ensure / get
    # ------------------------------------------------------------------ #

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owner_usernames: list[str] | None = None,
        collection_name: str | None = None,
    ) -> DocInfo:
        """创建 Document — collection_name 必须传（= Teamspace _id）。

        v1 不自动创建 default Teamspace，caller 必须先 create_collection 拿 space_id。
        """
        if not collection_name:
            raise ProviderError(
                "huly create_document 必须传 collection_name（= Teamspace space_id）"
            )
        pc = await self._ensure_client()
        try:
            doc_id = await pc.ops.create_doc(
                DOCUMENT_CLASS_DOCUMENT,
                collection_name,
                {
                    "title": title,
                    "content": markdown,
                    "parent": DOCUMENT_IDS_NO_PARENT,
                    "rank": str(int(time.time() * 1000)),
                },
            )
        except Exception as e:
            raise ProviderError(f"huly create_document 失败: {e}") from e
        return DocInfo(
            id=doc_id,
            url=self._build_doc_url(doc_id),
            title=title,
            provider=self.name,
        )

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None:
        """全量替换文档内容（+ 可选 title）。"""
        pc = await self._ensure_client()
        existing = await pc.rest.find_one(DOCUMENT_CLASS_DOCUMENT, {"_id": doc_id})
        if existing is None:
            raise ProviderError(f"huly update_document: doc {doc_id} 不存在")
        space = str(existing.get("space", ""))
        operations: dict[str, object] = {"content": markdown}
        if title is not None:
            operations["title"] = title
        try:
            await pc.ops.update_doc(DOCUMENT_CLASS_DOCUMENT, space, doc_id, operations)
        except Exception as e:
            raise ProviderError(f"huly update_document {doc_id} 失败: {e}") from e

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]:
        """跨 collection 列文档（v1 不做 title 模糊匹配，直接拉前 limit 个）。"""
        pc = await self._ensure_client()
        docs = await pc.rest.find_all(DOCUMENT_CLASS_DOCUMENT, None, {"limit": limit})
        return [
            DocInfo(
                id=str(d.get("_id", "")),
                url=self._build_doc_url(str(d.get("_id", ""))),
                title=str(d.get("title", "")),
                provider=self.name,
            )
            for d in docs[:limit]
        ]

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """v1 no-op — 用户身份通过 seed_huly_users.py 离线维护。"""
        usernames = [u.get("username", "") for u in users if u.get("username")]
        logger.debug(
            "[huly-doc] ensure_users() v1 no-op — 见 seed_huly_users.py（users=%d）",
            len(usernames),
        )
        return {"created": [], "skipped": usernames}

    async def get_document(self, doc_id: str) -> DocInfo | None:
        """获取文档元数据。不存在返回 None。"""
        pc = await self._ensure_client()
        doc = await pc.rest.find_one(DOCUMENT_CLASS_DOCUMENT, {"_id": doc_id})
        if doc is None:
            return None
        return DocInfo(
            id=doc_id,
            url=self._build_doc_url(doc_id),
            title=str(doc.get("title", "")),
            provider=self.name,
        )

    # ------------------------------------------------------------------ #
    # ABS-03 — 完整生命周期方法
    # ------------------------------------------------------------------ #

    async def create_collection(self, name: str, owner: str) -> str:
        """创建 Teamspace — return space_id。

        Args:
            name: Teamspace 显示名（如 "离职 · zhang.san"）
            owner: owner 业务 username（用 _resolve_account 解 AccountUuid）
        """
        pc = await self._ensure_client()
        owner_uuid = await self._resolve_account(pc, owner)
        bot = pc.bot_account
        members = [bot]
        if owner_uuid:
            members.append(owner_uuid)
        try:
            space_id = await pc.ops.create_doc(
                DOCUMENT_CLASS_TEAMSPACE,
                CORE_SPACE_SPACE,
                {
                    "name": name,
                    "description": "离职归档",
                    "private": False,
                    "archived": False,
                    "members": members,
                    "owners": [owner_uuid] if owner_uuid else [bot],
                    "autoJoin": False,
                    "type": DOCUMENT_TYPE_DEFAULT,
                },
            )
            return space_id
        except Exception as e:
            raise ProviderError(f"huly create_collection({name}) 失败: {e}") from e

    async def list_collections(self) -> list[dict]:
        """列出所有 Teamspace。"""
        pc = await self._ensure_client()
        spaces = await pc.rest.find_all(DOCUMENT_CLASS_TEAMSPACE, None, {"limit": 100})
        return [
            {
                "id": str(s.get("_id", "")),
                "name": str(s.get("name", "")),
                "provider": self.name,
            }
            for s in spaces
        ]

    async def delete_collection(self, collection_id: str) -> None:
        """删除整个 Teamspace（连带所有 Document）— 幂等。"""
        pc = await self._ensure_client()
        logger.warning("[huly-doc] 即将删 Teamspace %s（含所有文档）", collection_id)
        # 1. 列 + 逐个删 Document
        docs = await pc.rest.find_all(DOCUMENT_CLASS_DOCUMENT, {"space": collection_id})
        for d in docs:
            d_id = str(d.get("_id", ""))
            if d_id:
                try:
                    await pc.ops.remove_doc(DOCUMENT_CLASS_DOCUMENT, collection_id, d_id)
                except Exception as e:
                    logger.warning("[huly-doc] delete document %s 失败: %s", d_id, e)
        # 2. 删 Teamspace
        teamspace = await pc.rest.find_one(DOCUMENT_CLASS_TEAMSPACE, {"_id": collection_id})
        if teamspace is None:
            return  # 幂等
        try:
            await pc.ops.remove_doc(DOCUMENT_CLASS_TEAMSPACE, CORE_SPACE_SPACE, collection_id)
        except Exception as e:
            raise ProviderError(f"huly delete_collection {collection_id} 失败: {e}") from e

    async def list_documents_in_collection(
        self,
        *,
        collection_id: str,
        limit: int = 50,
    ) -> list[DocInfo]:
        pc = await self._ensure_client()
        docs = await pc.rest.find_all(
            DOCUMENT_CLASS_DOCUMENT, {"space": collection_id}, {"limit": limit}
        )
        return [
            DocInfo(
                id=str(d.get("_id", "")),
                url=self._build_doc_url(str(d.get("_id", ""))),
                title=str(d.get("title", "")),
                provider=self.name,
            )
            for d in docs[:limit]
        ]

    async def delete_document(self, doc_id: str) -> None:
        pc = await self._ensure_client()
        existing = await pc.rest.find_one(DOCUMENT_CLASS_DOCUMENT, {"_id": doc_id})
        if existing is None:
            return  # 幂等
        space = str(existing.get("space", ""))
        try:
            await pc.ops.remove_doc(DOCUMENT_CLASS_DOCUMENT, space, doc_id)
        except Exception as e:
            raise ProviderError(f"huly delete_document {doc_id} 失败: {e}") from e

    # ------------------------------------------------------------------ #
    # 内部 helper
    # ------------------------------------------------------------------ #

    async def _resolve_account(self, pc: HulyPlatformClient, username: str) -> str | None:
        """与 huly_im_provider._resolve_account 同语义（SocialIdentity → Employee mixin → personUuid）。"""
        from .huly.constants import DEMO_EMAIL_DOMAIN

        if not username:
            return None
        social_key = f"email:{username}@{DEMO_EMAIL_DOMAIN}"
        si = await pc.rest.find_one("contact:class:SocialIdentity", {"key": social_key})
        if not si:
            return None
        attached_to = si.get("attachedTo")
        if not attached_to:
            return None
        emp = await pc.rest.find_one("contact:mixin:Employee", {"_id": attached_to})
        if not emp:
            return None
        person_uuid = emp.get("personUuid")
        return str(person_uuid) if person_uuid else None
