"""钉钉 Provider — stub。

后续接入：
- 文档: 钉钉文档 (https://open.dingtalk.com/document)
- IM: /robot/send (机器人) 或 /message/sendBatchOToUser (应用消息)
- 鉴权: AppKey + AppSecret → access_token
"""

from __future__ import annotations

from .base import ProviderError


class DingTalkDocProvider:
    name = "dingtalk"

    async def create_document(self, *, title, markdown, owner_usernames=None):
        raise ProviderError("DingTalk doc provider not implemented yet (stub)")

    async def update_document(self, *, doc_id, markdown, title=None):
        raise ProviderError("DingTalk doc provider not implemented yet")

    async def list_documents(self, *, query=None, limit=10):
        return []

    async def ensure_users(self, users):
        return {"created": [], "skipped": [u.get("username", "?") for u in users]}

    async def get_document(self, doc_id):
        return None

    # ABS-03 — Phase 08-01 新增的 3 个生命周期方法（stub）
    async def delete_document(self, doc_id):
        raise ProviderError("DingTalk delete_document not implemented yet (stub)")

    async def list_documents_in_collection(self, *, collection_id, limit=50):
        return []

    async def delete_collection(self, collection_id):
        raise ProviderError("DingTalk delete_collection not implemented yet (stub)")


class DingTalkIMProvider:
    name = "dingtalk"

    def __init__(self) -> None:
        # ABS-04 — Phase 08-01 引入；stub 实现不需要 listener，但保留属性
        self._dispatch = None

    async def post_to_channel(self, channel_id, markdown):
        raise ProviderError("DingTalk IM provider not implemented yet (stub)")

    async def send_dm(self, username, markdown):
        raise ProviderError("DingTalk IM provider not implemented yet")

    async def ensure_user_in_channel(self, channel_id, username):
        pass

    async def list_team_users(self):
        return []

    async def resolve_username(self, username):
        return None

    def register_command_listener(self, dispatch) -> None:
        """ABS-04 — stub provider 不接收平台推送，仅保存引用供未来切换。"""
        self._dispatch = dispatch
