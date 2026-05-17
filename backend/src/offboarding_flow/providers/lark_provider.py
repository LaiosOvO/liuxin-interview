"""Lark / 飞书 DocProvider + IMProvider — 直调飞书 OpenAPI（不走 lark-mcp 进程）。

为什么不用 lark-openapi-mcp：
- lark-mcp 是 Node.js 进程，多一层 IPC + 依赖管理
- 飞书 OpenAPI 通过 tenant_access_token 调用直接、稳定
- 业务侧只用十几个 endpoints，自己 wrap 更可控
- 仍然把 LarkProvider 内部抽象成 tools，未来可以暴露成 MCP server

鉴权：
- 飞书企业自建 App → App ID + App Secret
- 内部 tenant_access_token 2h 自动刷新

国际版 lark.com vs 国内 feishu.cn — 用 LARK_BASE_URL env 切换。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from offboarding_flow.config import get_settings

from .base import DocInfo, ProviderError, UserInfo

logger = logging.getLogger(__name__)


class _LarkTokenCache:
    """tenant_access_token 缓存（自动刷新）。"""

    def __init__(self) -> None:
        self.token: str = ""
        self.expires_at: float = 0.0
        self._lock = asyncio.Lock()


_token_cache = _LarkTokenCache()


async def _get_tenant_token(base_url: str, app_id: str, app_secret: str) -> str:
    """拿 tenant_access_token，过期前 60s 自动刷新。"""
    if _token_cache.token and time.time() < _token_cache.expires_at - 60:
        return _token_cache.token
    async with _token_cache._lock:
        if _token_cache.token and time.time() < _token_cache.expires_at - 60:
            return _token_cache.token
        async with httpx.AsyncClient(base_url=base_url, timeout=10) as c:
            r = await c.post(
                "/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
        if r.status_code >= 400:
            raise ProviderError(f"lark token fetch {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("code") != 0:
            raise ProviderError(f"lark token err: {data}")
        _token_cache.token = data["tenant_access_token"]
        _token_cache.expires_at = time.time() + int(data.get("expire", 7200))
        return _token_cache.token


class _LarkBase:
    """共用 base — token 管理 + HTTP 客户端工厂。"""

    def __init__(self) -> None:
        s = get_settings()
        self._base = s.lark_base_url.rstrip("/")
        self._app_id = s.lark_app_id
        self._app_secret = s.lark_app_secret
        # 文档存放根目录（feishu Drive folder token）
        self._docs_folder_token = s.lark_docs_folder_token
        if not self._app_id or self._app_id.startswith("changeme"):
            raise ProviderError("LARK_APP_ID 未配置")

    async def _client(self) -> httpx.AsyncClient:
        token = await _get_tenant_token(self._base, self._app_id, self._app_secret)
        return httpx.AsyncClient(
            base_url=self._base,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
        client = await self._client()
        async with client:
            r = await client.request(method, path, json=json_body, params=params)
        if r.status_code >= 400:
            raise ProviderError(f"lark {method} {path} HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("code") not in (0, None):
            raise ProviderError(f"lark {path} business err: {data}")
        return data.get("data", data)


class LarkDocsProvider(_LarkBase):
    """飞书云文档 DocProvider — 用 docx_v1 API。"""

    name = "lark"

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owner_usernames: list[str] | None = None,
    ) -> DocInfo:
        body = {"title": title}
        if self._docs_folder_token:
            body["folder_token"] = self._docs_folder_token
        # 1. 创建空 docx
        try:
            data = await self._request("POST", "/open-apis/docx/v1/documents", json_body=body)
        except ProviderError:
            raise
        doc_id = data.get("document", {}).get("document_id", "")
        # 2. 用 import 接口写 markdown 内容
        # 飞书 docx 没有直接 markdown 导入；要 block-by-block 创建或用 wiki/sheets
        # 退而求其次：用 docs/v1/import (CSV/MD) 或直接用 sheets — 我们简化先写一个文本 block
        # （生产场景应该用 batch_update + 解析 markdown → blocks）
        if markdown:
            await self._append_text_block(doc_id, markdown)
        url = f"{self._base}/docx/{doc_id}"
        logger.info("[lark] docx created id=%s url=%s", doc_id, url)
        return DocInfo(id=doc_id, url=url, title=title, provider=self.name)

    async def _append_text_block(self, doc_id: str, markdown: str) -> None:
        """简化版：把整段 markdown 作为单个 text block 追加到 docx。

        生产场景应解析 markdown → multiple block types（heading/list/quote/etc）。
        当前 demo 阶段单 block 够用。
        """
        # 飞书 docx block API: POST /open-apis/docx/v1/documents/{doc_id}/blocks/{block_id}/children
        # 根 block_id = doc_id（约定）
        chunks = _chunk_text(markdown, 4500)  # 飞书单 block ≤5000 字符
        for chunk in chunks:
            block_body = {
                "index": -1,  # 追加到末尾
                "children": [
                    {
                        "block_type": 2,  # text block
                        "text": {
                            "elements": [
                                {"text_run": {"content": chunk, "text_element_style": {}}}
                            ],
                            "style": {},
                        },
                    }
                ],
            }
            try:
                await self._request(
                    "POST",
                    f"/open-apis/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    json_body=block_body,
                )
            except ProviderError as e:
                logger.warning("[lark] append text block failed: %s", e)
                break

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None:
        # 飞书 docx 全量替换比较复杂（要先删所有 children blocks 再加），暂作 append
        await self._append_text_block(doc_id, "\n\n---\n\n" + markdown)

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]:
        if not self._docs_folder_token:
            return []
        try:
            data = await self._request(
                "GET",
                "/open-apis/drive/v1/files",
                params={
                    "folder_token": self._docs_folder_token,
                    "page_size": min(limit, 50),
                },
            )
        except ProviderError as e:
            logger.warning("[lark] list_documents: %s", e)
            return []
        return [
            DocInfo(
                id=f.get("token", ""),
                url=f.get("url", ""),
                title=f.get("name", ""),
                provider=self.name,
            )
            for f in data.get("files", [])
            if f.get("type") == "docx"
        ]

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """飞书 user 由企业 IT 创建，不能 API 邀请。这里只查已存在的。"""
        skipped: list[str] = []
        for u in users:
            skipped.append(u.get("username", "?"))
        return {"created": [], "skipped": skipped}

    async def get_document(self, doc_id: str) -> DocInfo | None:
        try:
            data = await self._request("GET", f"/open-apis/docx/v1/documents/{doc_id}")
        except ProviderError:
            return None
        doc = data.get("document", {})
        return DocInfo(
            id=doc.get("document_id", doc_id),
            url=f"{self._base}/docx/{doc_id}",
            title=doc.get("title", ""),
            provider=self.name,
        )

    # ------------------------------------------------------------------ #
    # ABS-03 — 完整生命周期方法（Phase 08-01 新增）
    # ------------------------------------------------------------------ #

    async def delete_document(self, doc_id: str) -> None:
        """删除飞书 docx 文档（移入回收站）。

        飞书 API: DELETE /open-apis/drive/v1/files/{file_token}?type=docx
        - 文档不存在或已删 → 返回 ProviderError 时降级为 log warning + 不抛
        """
        try:
            await self._request(
                "DELETE",
                f"/open-apis/drive/v1/files/{doc_id}",
                params={"type": "docx"},
            )
            logger.info("[lark] docx deleted id=%s", doc_id)
        except ProviderError as e:
            # 飞书 99991663 = file not found；其他错误重抛
            msg = str(e).lower()
            if "not found" in msg or "99991663" in msg or "404" in msg:
                logger.info("[lark] docx %s 已不存在，删除视为成功", doc_id)
                return
            raise

    async def list_documents_in_collection(
        self,
        *,
        collection_id: str,
        limit: int = 50,
    ) -> list[DocInfo]:
        """列出指定 folder 下的所有 docx 文档（飞书 folder 即 collection）。"""
        try:
            data = await self._request(
                "GET",
                "/open-apis/drive/v1/files",
                params={
                    "folder_token": collection_id,
                    "page_size": min(limit, 50),
                },
            )
        except ProviderError as e:
            logger.warning("[lark] list_documents_in_collection: %s", e)
            return []
        return [
            DocInfo(
                id=f.get("token", ""),
                url=f.get("url", ""),
                title=f.get("name", ""),
                provider=self.name,
            )
            for f in data.get("files", [])
            if f.get("type") == "docx"
        ]

    async def delete_collection(self, collection_id: str) -> None:
        """删除飞书 folder（连带下面所有文档移到回收站）。

        飞书 API: DELETE /open-apis/drive/v1/files/{folder_token}?type=folder
        ⚠️ 危险操作 — 调用方须有审计追踪。
        """
        logger.warning("[lark] 即将删除 folder %s（含所有 docx 文档）", collection_id)
        try:
            await self._request(
                "DELETE",
                f"/open-apis/drive/v1/files/{collection_id}",
                params={"type": "folder"},
            )
            logger.info("[lark] folder deleted id=%s", collection_id)
        except ProviderError as e:
            msg = str(e).lower()
            if "not found" in msg or "99991663" in msg or "404" in msg:
                logger.info("[lark] folder %s 已不存在，删除视为成功", collection_id)
                return
            raise


class LarkIMProvider(_LarkBase):
    """飞书 IM Provider — 群消息 / 私聊 / @mention。"""

    name = "lark"

    def __init__(self) -> None:
        super().__init__()
        # ABS-04 — Phase 08-01 引入；当前 Lark IM 走 webhook 模式，listener 反向订阅
        # 由独立的 huly_listener / lark_listener 承担；本 Provider 暂保留属性 + no-op hook
        self._dispatch = None

    def register_command_listener(self, dispatch) -> None:
        """ABS-04 — Lark Provider 仅做 REST 推送 / 查询；listener 反向订阅
        由 future LarkListener 承担。
        """
        self._dispatch = dispatch

    async def post_to_channel(self, channel_id: str, markdown: str) -> None:
        """发到群（chat_id 用飞书 chat open_id）。markdown 转富文本卡片。"""
        body = {
            "receive_id": channel_id,
            "msg_type": "interactive",
            "content": _markdown_to_card(markdown),
        }
        await self._request(
            "POST",
            "/open-apis/im/v1/messages",
            json_body=body,
            params={"receive_id_type": "chat_id"},
        )

    async def send_dm(self, username: str, markdown: str) -> None:
        """按 username（飞书登录 ID）→ open_id → 发私聊。"""
        user = await self.resolve_username(username)
        if user is None:
            raise ProviderError(f"lark user not found: {username}")
        body = {
            "receive_id": user.id,
            "msg_type": "interactive",
            "content": _markdown_to_card(markdown),
        }
        await self._request(
            "POST",
            "/open-apis/im/v1/messages",
            json_body=body,
            params={"receive_id_type": "open_id"},
        )

    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        user = await self.resolve_username(username)
        if user is None:
            return
        try:
            await self._request(
                "POST",
                f"/open-apis/im/v1/chats/{channel_id}/members",
                json_body={"id_list": [user.id]},
                params={"member_id_type": "open_id"},
            )
        except ProviderError as e:
            logger.debug("[lark] add user to chat: %s", e)

    async def list_team_users(self) -> list[UserInfo]:
        """飞书拉部门下所有 user — 需要 department_id（默认根 0）。"""
        try:
            data = await self._request(
                "GET",
                "/open-apis/contact/v3/users/find_by_department",
                params={"department_id": "0", "page_size": 50},
            )
        except ProviderError as e:
            logger.warning("[lark] list_team_users: %s", e)
            return []
        return [
            UserInfo(
                id=u.get("open_id", ""),
                username=u.get("user_id", ""),  # 飞书 user_id（企业内唯一）
                email=u.get("email", "") or u.get("enterprise_email", ""),
                name=u.get("name", ""),
                provider=self.name,
            )
            for u in data.get("items", [])
        ]

    async def resolve_username(self, username: str) -> UserInfo | None:
        """按 user_id 查（飞书有 user_id / open_id / union_id 多种 ID）。"""
        try:
            data = await self._request(
                "GET",
                f"/open-apis/contact/v3/users/{username}",
                params={"user_id_type": "user_id"},
            )
        except ProviderError:
            return None
        u = data.get("user", {})
        return UserInfo(
            id=u.get("open_id", ""),
            username=u.get("user_id", username),
            email=u.get("email", "") or u.get("enterprise_email", ""),
            name=u.get("name", ""),
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    cur = ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > max_chars:
            chunks.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        chunks.append(cur)
    return chunks


def _markdown_to_card(markdown: str) -> str:
    """把 markdown 包装成飞书 interactive 卡片 JSON 字符串。"""
    import json as _json

    return _json.dumps(
        {
            "config": {"wide_screen_mode": True},
            "elements": [
                {
                    "tag": "markdown",
                    "content": markdown[:9000],  # 飞书卡片单元素 ≤10000 字符
                }
            ],
        },
        ensure_ascii=False,
    )
