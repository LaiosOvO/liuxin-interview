"""通知通道实现（Phase 4 双通道：Mattermost + Email）。

Slice 4B：Mattermost 出站（PAT 调 /api/v4/posts + Interactive Message attachments）
"""

from .mattermost_sender import (
    MattermostMessage,
    MattermostSender,
    MattermostSendError,
    build_action_attachment,
)

__all__ = [
    "MattermostMessage",
    "MattermostSendError",
    "MattermostSender",
    "build_action_attachment",
]
