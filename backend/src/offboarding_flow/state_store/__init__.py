"""业务表 state_store 模块。

提供 SQLAlchemy 2.x async ORM + Repository 层 + 异步 session 工厂。

约定（CONTEXT §2 + §3.3）：
- 所有业务表在 `app` schema（与 LangGraph 的 `langgraph` schema 隔离）
- Repository 用 PG ON CONFLICT 实现 upsert 幂等（PITFALLS #16）
- 所有 id 用 uuid4 默认值（PITFALLS #17 防自增并行冲突）
"""

from .enums import (
    ActionStatus,
    ActionType,
    FlowStatus,
    NodeStatus,
    NotificationChannel,
    NotificationStatus,
    Role,
)
from .models import (
    ActionLog,
    Base,
    FlowInstance,
    NodeState,
    Notification,
    NotificationOutbox,
    User,
)
from .repositories import (
    ActionRepository,
    FlowRepository,
    NodeRepository,
    UserRepository,
)
from .session import dispose_engine, get_engine, get_session, get_sessionmaker, init_db

__all__ = [
    # enums
    "ActionStatus",
    "ActionType",
    "FlowStatus",
    "NodeStatus",
    "NotificationChannel",
    "NotificationStatus",
    "Role",
    # models
    "ActionLog",
    "Base",
    "FlowInstance",
    "NodeState",
    "Notification",
    "NotificationOutbox",
    "User",
    # repositories
    "ActionRepository",
    "FlowRepository",
    "NodeRepository",
    "UserRepository",
    # session
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
    "init_db",
]
