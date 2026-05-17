"""企业微信 Provider — stub。

后续接入参考：
- 文档: WPS 在线文档 / 腾讯文档（企微集成）
- IM:  /cgi-bin/message/send (Robot Webhook 或 应用消息)
- 鉴权: corpid + corpsecret → access_token
"""

from __future__ import annotations

import logging

from .base import DocInfo, ProviderError, UserInfo

logger = logging.getLogger(__name__)


class WeComDocProvider:
    name = "wecom"

    async def create_document(self, *, title: str, markdown: str, owner_usernames=None) -> DocInfo:
        raise ProviderError("WeCom doc provider not implemented yet (stub)")

    async def update_document(self, *, doc_id, markdown, title=None) -> None:
        raise ProviderError("WeCom doc provider not implemented yet")

    async def list_documents(self, *, query=None, limit=10) -> list[DocInfo]:
        return []

    async def ensure_users(self, users):
        return {"created": [], "skipped": [u.get("username", "?") for u in users]}

    async def get_document(self, doc_id):
        return None

    # ABS-03 — Phase 08-01 新增的 3 个生命周期方法（stub）
    async def delete_document(self, doc_id):
        raise ProviderError("WeCom delete_document not implemented yet (stub)")

    async def list_documents_in_collection(self, *, collection_id, limit=50):
        return []

    async def delete_collection(self, collection_id):
        raise ProviderError("WeCom delete_collection not implemented yet (stub)")


class WeComIMProvider:
    name = "wecom"

    def __init__(self) -> None:
        # ABS-04 — Phase 08-01 引入；stub 实现不需要 listener，但保留属性
        self._dispatch = None

    async def post_to_channel(self, channel_id, markdown):
        raise ProviderError("WeCom IM provider not implemented yet (stub)")

    async def send_dm(self, username, markdown):
        raise ProviderError("WeCom IM provider not implemented yet")

    async def ensure_user_in_channel(self, channel_id, username):
        pass

    async def list_team_users(self) -> list[UserInfo]:
        return []

    async def resolve_username(self, username):
        return None

    def register_command_listener(self, dispatch) -> None:
        """ABS-04 — stub provider 不接收平台推送，仅保存引用供未来切换。"""
        self._dispatch = dispatch
