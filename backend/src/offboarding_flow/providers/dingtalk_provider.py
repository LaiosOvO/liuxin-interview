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


class DingTalkIMProvider:
    name = "dingtalk"

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
