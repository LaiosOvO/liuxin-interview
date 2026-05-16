"""Provider 抽象 — DocProvider（协作文档）+ IMProvider（即时通讯）。

Protocol 设计哲学：
- 业务层（meeting_service / flow node）依赖抽象，不依赖具体实现
- 一个 Provider 内部可以同时处理 user / channel / document（如 Lark 把这些都在一个 App 下）
- 失败行为统一：失败抛 ProviderError；可选操作（如 ensure_user_in_channel）失败仅 log
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """Provider 调用失败的统一异常基类。"""


@dataclass(frozen=True)
class DocInfo:
    """协作文档元数据（跨平台通用结构）。"""

    id: str  # 平台内 doc id
    url: str  # 完整可访问 URL
    title: str
    provider: str  # "outline" | "lark" | "wecom" | "dingtalk"


@dataclass(frozen=True)
class UserInfo:
    """user 元数据（跨平台通用）。"""

    id: str  # 平台内 user id（飞书 open_id / MM uuid 等）
    username: str
    email: str
    name: str
    provider: str


@runtime_checkable
class DocProvider(Protocol):
    """协作文档平台抽象。

    实现：OutlineProvider / LarkDocsProvider / WeComDriveProvider / DingTalkProvider
    """

    name: str  # "outline" | "lark" | "wecom" | "dingtalk"

    async def create_document(
        self,
        *,
        title: str,
        markdown: str,
        owner_usernames: list[str] | None = None,
    ) -> DocInfo:
        """创建一篇协作文档。失败抛 ProviderError。"""
        ...

    async def update_document(
        self,
        *,
        doc_id: str,
        markdown: str,
        title: str | None = None,
    ) -> None:
        """全量替换文档内容。"""
        ...

    async def list_documents(
        self,
        *,
        query: str | None = None,
        limit: int = 10,
    ) -> list[DocInfo]:
        """列出文档（可选模糊搜索）。"""
        ...

    async def ensure_users(self, users: list[dict[str, str]]) -> dict[str, list[str]]:
        """同步外部 user 到平台（已存在的 skip）。

        users 项: {username, email, name, role}
        返回: {"created": [usernames], "skipped": [usernames]}
        """
        ...

    async def get_document(self, doc_id: str) -> DocInfo | None:
        """获取文档信息（不含内容）。不存在返回 None。"""
        ...


@runtime_checkable
class IMProvider(Protocol):
    """IM 平台抽象（消息推送 + 频道成员管理 + user 查询）。

    实现：MattermostProvider / LarkIMProvider / WeComIMProvider / DingTalkIMProvider
    """

    name: str

    async def post_to_channel(self, channel_id: str, markdown: str) -> None:
        """向指定 channel/group 发消息（支持 markdown）。"""
        ...

    async def send_dm(self, username: str, markdown: str) -> None:
        """私聊推送（按 username 找 user → 创建/获取 DM channel → POST）。"""
        ...

    async def ensure_user_in_channel(self, channel_id: str, username: str) -> None:
        """把 user 加入 channel（已是成员幂等）。"""
        ...

    async def list_team_users(self) -> list[UserInfo]:
        """拉所有 team 成员（用于 sync）。"""
        ...

    async def resolve_username(self, username: str) -> UserInfo | None:
        """按 username 查 user info。"""
        ...
