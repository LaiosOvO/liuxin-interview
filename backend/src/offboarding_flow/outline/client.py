"""Outline REST API 客户端 — 创建/搜索/分享文档。

约定：
- 异步 httpx；统一 base_url；token 走 Bearer header
- 失败抛 OutlineError（不暴露 httpx 内部异常）
- POST endpoints 都用 JSON body（Outline 风格：方法名作为 URL 后缀）

参考：https://www.getoutline.com/developers
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

import httpx

from offboarding_flow.config import get_settings

logger = logging.getLogger(__name__)


class OutlineError(Exception):
    """Outline 调用失败。"""


class OutlineClient:
    """轻量 Outline 客户端。"""

    def __init__(self, base_url: str, api_token: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/api",
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=self._timeout,
        )

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with self._client() as c:
            try:
                resp = await c.post(path, json=body)
            except httpx.HTTPError as e:
                raise OutlineError(f"Outline 调用失败 {path}: {e}") from e
        if resp.status_code >= 400:
            raise OutlineError(f"Outline {path} HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        if not data.get("ok", True) and "data" not in data:
            raise OutlineError(f"Outline {path} returned not-ok: {data}")
        return data.get("data", data)

    # ------------------------------------------------------------------ #
    # documents
    # ------------------------------------------------------------------ #

    async def create_document(
        self,
        *,
        title: str,
        text: str,
        collection_id: str,
        publish: bool = True,
        parent_document_id: str | None = None,
    ) -> dict[str, Any]:
        """创建文档并发布（publish=True 后立即可访问）。返回 doc 对象（含 id/url/urlId）。"""
        body: dict[str, Any] = {
            "title": title,
            "text": text,
            "collectionId": collection_id,
            "publish": publish,
        }
        if parent_document_id:
            body["parentDocumentId"] = parent_document_id
        doc = await self._post("/documents.create", body)
        logger.info(
            "[outline] doc created id=%s url=%s title=%r",
            doc.get("id"),
            doc.get("url"),
            title[:40],
        )
        return doc

    async def update_document(
        self,
        *,
        document_id: str,
        text: str,
        title: str | None = None,
        append: bool = False,
        publish: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "id": document_id,
            "text": text,
            "append": append,
            "publish": publish,
        }
        if title:
            body["title"] = title
        return await self._post("/documents.update", body)

    async def get_document(self, document_id: str) -> dict[str, Any]:
        return await self._post("/documents.info", {"id": document_id})

    async def search_documents(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._post("/documents.search", {"query": query, "limit": limit})
        return data if isinstance(data, list) else data.get("results", [])

    # ------------------------------------------------------------------ #
    # users
    # ------------------------------------------------------------------ #

    async def list_users(self, limit: int = 100) -> list[dict[str, Any]]:
        async with self._client() as c:
            resp = await c.post("/users.list", json={"limit": limit})
        if resp.status_code >= 400:
            raise OutlineError(f"users.list HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("data", [])

    async def invite_users(self, invites: list[dict[str, str]]) -> dict[str, Any]:
        """批量邀请 user。invites=[{email, name, role}]。已存在的会在 unsent 里。

        role: "admin" | "member" | "viewer"（默认 member）
        """
        body = {"invites": invites}
        return await self._post("/users.invite", body)

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """幂等同步：对比已有 → 缺的 invite。
        users=[{username, email, name, role}]
        返回 {"created": [...usernames], "skipped": [...usernames]}
        """
        existing = await self.list_users(limit=100)
        existing_emails = {u.get("email", "").lower() for u in existing if u.get("email")}
        to_invite = []
        skipped: list[str] = []
        import re as _re

        EMAIL_RE = _re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
        for u in users:
            email = u.get("email", "").lower()
            if not EMAIL_RE.match(email):
                skipped.append(f"{u.get('username','?')}(invalid_email)")
                continue
            if email in existing_emails:
                skipped.append(u.get("username", email))
                continue
            to_invite.append(
                {
                    "email": u["email"],
                    "name": u.get("name", u.get("username", email)),
                    "role": u.get("role", "member"),
                }
            )
        created: list[str] = []
        if to_invite:
            result = await self.invite_users(to_invite)
            for u in result.get("users", []):
                created.append(u.get("email", "?"))
        return {"created": created, "skipped": skipped}

    # ------------------------------------------------------------------ #
    # collections
    # ------------------------------------------------------------------ #

    async def list_collections(self, limit: int = 25) -> list[dict[str, Any]]:
        async with self._client() as c:
            resp = await c.post("/collections.list", json={"limit": limit})
        if resp.status_code >= 400:
            raise OutlineError(f"collections.list HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json().get("data", [])

    async def create_collection(
        self,
        *,
        name: str,
        description: str = "",
        permission: str = "read_write",
    ) -> dict[str, Any]:
        """新建一个 collection（文档分类）。permission: read | read_write | None（None=私有）。"""
        body = {"name": name, "description": description, "permission": permission}
        col = await self._post("/collections.create", body)
        logger.info("[outline] collection created id=%s name=%r", col.get("id"), name)
        return col

    async def ensure_collection(self, name: str) -> dict[str, Any]:
        """按名称幂等查找/创建 collection。返回 collection 对象。

        limit=100 是 Outline API 单次 list 上限；超过这个数量需要 paginate，
        但本系统短期内不会有那么多 collection（每离职员工 1 个 + 全局 2 个）。
        """
        existing = await self.list_collections(limit=100)
        for col in existing:
            if col.get("name") == name:
                return col
        return await self.create_collection(name=name, description=f"自动创建: {name}")


# ---------------------------------------------------------------------------
# 单例（lru_cache）
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_outline_client() -> OutlineClient:
    settings = get_settings()
    base_url = settings.outline_url
    token = settings.outline_api_token
    if not base_url or not token or token.startswith("changeme"):
        raise OutlineError("OUTLINE_URL / OUTLINE_API_TOKEN 未配置")
    return OutlineClient(base_url=base_url, api_token=token)


def reset_outline_client() -> None:
    """测试用：清缓存。"""
    get_outline_client.cache_clear()
