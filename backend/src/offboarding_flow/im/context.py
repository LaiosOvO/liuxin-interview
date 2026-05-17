"""IMHelpers — 命令 handler 用以"回写消息"的回调集合（ABS-02 / Plan 02 ABS-05）。

设计要点：
- `frozen=True` dataclass：单测 mock 时类型安全 + 防 handler 内意外改字段。
- 每个 IM listener 在调 `dispatch_message` 时自己构造一份 IMHelpers，
  把平台特定的回写 API（如 MM 的 `driver.posts.create_post`）封装成
  统一的 `Callable[[str, str], Awaitable[None]]`。
- `ensure_in_channel` 是可选的（部分 IM 平台无 channel 成员管理概念，可为 None）。

注意：
- 本 plan（08-01）暂不把 IMHelpers 塞进 `BotInvocationContext`（保持 Phase 7
  `bot_service.py` 的 `mm_helpers: dict | None` 字段不动，避免 11 个命令 handler
  改 import）。
- Plan 02（ABS-05 HandlerRegistry 重构）会把 `BotInvocationContext.mm_helpers`
  → `im_helpers: IMHelpers` 一并改造，并迁移现有 handler。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

# 频道/DM 内回写文本（channel_id, markdown_text）→ None
PostFn = Callable[[str, str], Awaitable[None]]
# 给指定 username 发 DM（username, markdown_text）→ None
DmFn = Callable[[str, str], Awaitable[None]]
# 把 user 加进 channel（channel_id, username）→ None；可选
EnsureFn = Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class IMHelpers:
    """每个 IM 平台 listener 注入的"回写回调"集合。

    Attributes:
        post_channel: 在原 channel/DM 内回复一条 markdown 消息（兼 DM / 公开频道 / 私有频道）。
        send_dm: 按 username 找用户并发 1:1 DM。
        ensure_in_channel: 把指定 username 加进 channel（用于 @mention 触发通知）。
            可选 — 部分平台无此概念（如 Huly Card 评论），实现方传 None 即可。
    """

    post_channel: PostFn
    send_dm: DmFn
    ensure_in_channel: EnsureFn | None = None


__all__ = ["IMHelpers", "PostFn", "DmFn", "EnsureFn"]
