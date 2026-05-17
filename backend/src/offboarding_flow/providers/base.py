"""Provider 抽象 — DocProvider（协作文档）+ IMProvider（即时通讯）。

Protocol 设计哲学：
- 业务层（meeting_service / flow node）依赖抽象，不依赖具体实现
- 一个 Provider 内部可以同时处理 user / channel / document（如 Lark 把这些都在一个 App 下）
- 失败行为统一：失败抛 ProviderError；可选操作（如 ensure_user_in_channel）失败仅 log

Phase 08-01（ABS-03 / ABS-04）扩展：
- DocProvider 补 3 个生命周期方法 — delete_document / list_documents_in_collection / delete_collection
  目的：让 Huly Space-per-employee 模式有完整的 CRUD 闭环（创建员工 Space → 写交接文档 →
  归档后删 Space），与 Outline collection 模型对齐。
- IMProvider 加 register_command_listener — 统一 listener 反向订阅 hook，与 IMListener Protocol 对齐
  目的：未来切换 IM 平台（Mattermost → Huly / Lark），bot 命令分发逻辑 0 改动。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

# 反向订阅 dispatch 的可调用签名（实际签名见 im.dispatcher.dispatch_message）。
# 与 im.protocol.DispatchFn 同结构；这里独立定义避免 providers 模块依赖 im 模块。
DispatchFn = Callable[..., Awaitable[None]]


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
class CollectionInfo:
    """协作文档 collection / space 元数据（跨平台通用，ABS-03 新增）。

    Outline → collection；Huly → Space；Lark → folder；钉钉/企微 → 知识库。
    """

    id: str
    name: str
    provider: str


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

    Phase 08-01 ABS-03 — 补 3 个生命周期方法 (delete_document / list_documents_in_collection /
    delete_collection)，让 Huly Space-per-employee 与 Outline collection 走同一闭环。
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

    # ------------------------------------------------------------------ #
    # ABS-03 — 完整生命周期方法（Phase 08-01 新增）
    # ------------------------------------------------------------------ #

    async def delete_document(self, doc_id: str) -> None:
        """删除指定文档。不存在视为成功（幂等）；其他失败抛 ProviderError。

        典型场景：流程 archive 后清理临时草稿；员工撤销离职申请回滚刚创建的文档。
        """
        ...

    async def list_documents_in_collection(
        self,
        *,
        collection_id: str,
        limit: int = 50,
    ) -> list[DocInfo]:
        """列出指定 collection / Space / folder 下的所有文档。

        与 list_documents 区别：后者跨 collection 模糊搜索，前者限定单 collection。
        典型场景：HR 看某员工独立 Space 下的 11 个节点交接文档；运维清理 archive 流程的所有副本。
        """
        ...

    async def delete_collection(self, collection_id: str) -> None:
        """删除整个 collection / Space / folder（连带所有文档）。

        不存在视为成功（幂等）；其他失败抛 ProviderError。
        典型场景：员工离职归档后清理 Huly Space；定期清理临时 demo collection。

        ⚠️ 实现方应在删除前 log warning + 确保调用方有审计追踪；本 Protocol 不强制审计。
        """
        ...


@runtime_checkable
class IMProvider(Protocol):
    """IM 平台抽象（消息推送 + 频道成员管理 + user 查询）。

    实现：MattermostProvider / LarkIMProvider / WeComIMProvider / DingTalkIMProvider

    Phase 08-01 ABS-04 — 加 register_command_listener 反向订阅 hook，
    与 IMListener Protocol 对齐（让 Provider 也能承担 listener 角色）。
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

    # ------------------------------------------------------------------ #
    # ABS-04 — listener 反向订阅 hook（Phase 08-01 新增）
    # ------------------------------------------------------------------ #

    def register_command_listener(self, dispatch: DispatchFn) -> None:
        """统一 listener 反向订阅 hook — 与 IMListener Protocol 对齐。

        让 Provider 实现可承担 listener 角色（如 Huly Provider 同时是 Webhook 接收方）。
        Provider 不需要长连接时（如 Mattermost Provider 走 REST API），实现为 no-op 即可。

        Args:
            dispatch: 通常即 im.dispatcher.dispatch_message；当 Provider 收到平台
                推送（Webhook / WS event）时调用 dispatch 转交业务编排。
        """
        ...
