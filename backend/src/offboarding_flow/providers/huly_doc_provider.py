"""Huly DocProvider — 通过 httpx 调 huly-bridge sidecar 实现 DocProvider Protocol。

Phase 8 / HULY-06 / Plan 05 Task 3

设计：
- 所有 doc 操作走 sidecar `http://huly-bridge:7777/api/doc/*` 路由
- BRIDGE_TOKEN 通过 X-Bridge-Token header 注入
- 与 sidecar src/doc.ts 对齐：
  - POST   /api/doc/create_space     body {name, owner_username}        → {space_id}
  - POST   /api/doc/create_doc       body {space_id, title, markdown}    → {doc_id, url, title}
  - GET    /api/doc/list_in_space    query space_id                       → {docs: [...]}
  - DELETE /api/doc/document         query id                             → {deleted: bool}
  - DELETE /api/doc/space            query id                             → {deleted, documents_removed}

ABS-03 — 完整生命周期：含 delete_collection / list_documents_in_collection / delete_document
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from offboarding_flow.config import Settings

from .base import DocInfo, ProviderError

logger = logging.getLogger(__name__)


class HulyDocProvider:
    """Huly 实现的 DocProvider — HTTP 转发到 huly-bridge sidecar。"""

    name = "huly"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = settings.huly_bridge_url.rstrip("/")
        self._token = settings.huly_bridge_token
        self._timeout = settings.huly_bridge_http_timeout

    # ------------------------------------------------------------------ #
    # 共享 httpx 客户端
    # ------------------------------------------------------------------ #

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Content-Type": "application/json",
                "X-Bridge-Token": self._token,
            },
            timeout=self._timeout,
        )

    @staticmethod
    def _ensure_ok(action: str, response: httpx.Response) -> dict[str, Any]:
        """统一解析 sidecar envelope。"""
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = {}
            code = body.get("code", "HTTP_ERROR")
            error = body.get("error", response.text[:200])
            raise ProviderError(f"huly {action} 失败 ({response.status_code} {code}): {error}")
        try:
            payload = response.json()
        except Exception as e:
            raise ProviderError(f"huly {action} 响应非 JSON: {e}") from e
        if not payload.get("ok"):
            raise ProviderError(
                f"huly {action} 失败: {payload.get('error', 'unknown')} "
                f"(code={payload.get('code', 'UNKNOWN')})"
            )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

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
        """创建一篇 Document。

        Huly 语义：Document 必须挂在某 Teamspace 之下；本方法采用约定 — 若 caller 不传 collection
        信息则用 HulyDocProvider 的 default Teamspace（v1 不实现 — caller 必须配合 create_collection
        先创 Teamspace 再 create_document）。

        当前实现：把 collection_name 当作 space_id 传入（Plan 06 重构成完整 Teamspace 模型）。
        """
        if not collection_name:
            raise ProviderError(
                "huly create_document 必须传 collection_name（= Teamspace space_id）— "
                "请先 create_collection 拿到 space_id"
            )
        async with self._client() as c:
            r = await c.post(
                "/api/doc/create_doc",
                json={"space_id": collection_name, "title": title, "markdown": markdown},
            )
        data = self._ensure_ok("create_doc", r)
        return DocInfo(
            id=data.get("doc_id", ""),
            url=data.get("url", ""),
            title=data.get("title", title),
            provider=self.name,
        )

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None:
        """更新文档 — v1 stub（Plan 05 sidecar 暂未实现 update_doc 端点，Plan 06 补）。"""
        logger.warning(
            "[huly-doc-provider] update_document v1 未实现（sidecar 待补端点）；doc_id=%s",
            doc_id,
        )
        raise ProviderError(
            "huly update_document v1 未实现 — 待 Plan 06 补 sidecar POST /api/doc/update_doc 端点"
        )

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]:
        """跨 collection 模糊搜索 — v1 返回空列表（Plan 06 实现）。"""
        logger.warning(
            "[huly-doc-provider] list_documents v1 返回 [] — 请用 list_documents_in_collection"
        )
        return []

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """v1 sidecar 不暴露 user 创建 — Plan 06 由 seed_huly_users.py 离线维护。"""
        usernames = [u.get("username", "") for u in users if u.get("username")]
        logger.warning(
            "[huly-doc-provider] ensure_users v1 no-op（Plan 06 通过 seed 脚本维护）— users=%s",
            usernames,
        )
        return {"created": [], "skipped": usernames}

    async def get_document(self, doc_id: str) -> DocInfo | None:
        """获取文档元数据 — v1 stub（sidecar 暂未实现 GET /api/doc/document）。"""
        logger.warning(
            "[huly-doc-provider] get_document v1 stub 返回 None；doc_id=%s",
            doc_id,
        )
        return None

    # ------------------------------------------------------------------ #
    # ABS-03 — 完整生命周期方法（Phase 08-01 新增）
    # ------------------------------------------------------------------ #

    async def create_collection(self, name: str, owner: str) -> str:
        """创建 Teamspace — POST /api/doc/create_space。

        Args:
            name: Teamspace 显示名（如 "离职 · zhang.san"）
            owner: owner 业务 username
        Returns:
            space_id（Huly Teamspace _id）
        """
        async with self._client() as c:
            r = await c.post(
                "/api/doc/create_space",
                json={"name": name, "owner_username": owner},
            )
        data = self._ensure_ok("create_space", r)
        return data.get("space_id", "")

    async def list_collections(self) -> list[dict]:
        """列出所有 Teamspace — v1 stub 返回 []（sidecar 暂未实现 GET /api/doc/spaces）。

        Plan 06 seed 后业务层从 DB users 表自己维护 user → space_id 映射即可。
        """
        logger.warning(
            "[huly-doc-provider] list_collections v1 返回 [] — 待 Plan 06 补 sidecar 端点"
        )
        return []

    async def delete_collection(self, collection_id: str) -> None:
        """删除整个 Teamspace（含所有文档）— DELETE /api/doc/space?id={collection_id}。"""
        logger.warning("[huly-doc-provider] 即将删除 Teamspace %s（含所有文档）", collection_id)
        async with self._client() as c:
            r = await c.delete("/api/doc/space", params={"id": collection_id})
        self._ensure_ok("delete_space", r)

    async def list_documents_in_collection(
        self,
        *,
        collection_id: str,
        limit: int = 50,
    ) -> list[DocInfo]:
        """列出某 Teamspace 下所有 Document — GET /api/doc/list_in_space?space_id={...}。"""
        async with self._client() as c:
            r = await c.get(
                "/api/doc/list_in_space",
                params={"space_id": collection_id},
            )
        data = self._ensure_ok("list_in_space", r)
        docs_raw = data.get("docs") or []
        if not isinstance(docs_raw, list):
            return []
        results: list[DocInfo] = []
        for d in docs_raw[:limit]:
            if not isinstance(d, dict):
                continue
            results.append(
                DocInfo(
                    id=str(d.get("id", "")),
                    url=str(d.get("url", "")),
                    title=str(d.get("title", "")),
                    provider=self.name,
                )
            )
        return results

    async def delete_document(self, doc_id: str) -> None:
        """删除单篇文档 — DELETE /api/doc/document?id={doc_id}（404 视为幂等成功）。"""
        async with self._client() as c:
            r = await c.delete("/api/doc/document", params={"id": doc_id})
        # sidecar 端不存在时返回 200 + deleted=false，不需要特殊处理
        self._ensure_ok("delete_document", r)
