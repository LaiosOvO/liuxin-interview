"""业务表枚举值集中定义（CONTEXT §7）。

约定：
- 用 StrEnum（Python 3.12+）保证 .value 是 str，方便序列化
- 列名 / 值与 SQL 一致（避免 ORM 转换不必要的复杂度）
"""

from __future__ import annotations

from enum import StrEnum


class FlowStatus(StrEnum):
    """flow_instances.status 枚举。"""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class NodeStatus(StrEnum):
    """node_states.status 枚举（CONTEXT §7）。"""

    PENDING = "pending"
    WAITING_HUMAN = "waiting_human"
    IN_REVIEW = "in_review"
    DONE = "done"
    REJECTED = "rejected"
    RETURNED = "returned"


class ActionType(StrEnum):
    """action_logs.action 枚举（PRD §4.2 三态决策 + system 系统动作）。"""

    ADVANCE = "advance"
    RETURN = "return"
    REJECT = "reject"
    RESTART = "restart"
    SYSTEM = "system"


class ActionStatus(StrEnum):
    """action_logs.status 枚举（双写规范的失败补偿 — Phase 2 完善）。"""

    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"


class NotificationChannel(StrEnum):
    """notifications/notification_outbox.channel 枚举（Phase 4 才用）。"""

    EMAIL = "email"
    MATTERMOST = "mattermost"


class NotificationStatus(StrEnum):
    """notifications/notification_outbox.status 枚举。"""

    PENDING = "pending"
    PROCESSING = "processing"
    SENT = "sent"
    FAILED = "failed"


class Role(StrEnum):
    """users.role 枚举（PRD §6.2 + SEED-02 8 角色）。"""

    APPLICANT = "applicant"
    MANAGER = "manager"
    HR = "hr"
    IT_ADMIN = "it_admin"
    FINANCE = "finance"
    LEGAL = "legal"
    KB_OWNER = "kb_owner"
    ARCHIVIST = "archivist"
    ADMIN = "admin"
