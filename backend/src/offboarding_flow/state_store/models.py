"""业务表 SQLAlchemy 2.x ORM 模型（CONTEXT §7 + PRD §6.1）。

约定：
- 所有表在 `app` schema（与 LangGraph `langgraph` schema 隔离）
- 所有 id 用 UUID PK + server_default=gen_random_uuid()（PITFALLS #17）
- 所有时间列用 TIMESTAMP WITH TIME ZONE + server_default=func.now()
- 用 Mapped/mapped_column 风格（SQLAlchemy 2.x 推荐）
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """SQLAlchemy 2.x DeclarativeBase 基类。"""


# ---------------------------------------------------------------------------
# 1. flow_instances —— 流程实例（PRD §6.1）
# ---------------------------------------------------------------------------
class FlowInstance(Base):
    """离职流程实例。"""

    __tablename__ = "flow_instances"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    employee_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=text("'standard_offboarding'")
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'in_progress'"), index=True
    )
    context: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    nodes: Mapped[list["NodeState"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", lazy="selectin"
    )
    actions: Mapped[list["ActionLog"]] = relationship(
        back_populates="flow", cascade="all, delete-orphan", lazy="noload"
    )


# ---------------------------------------------------------------------------
# 2. node_states —— 节点状态
# ---------------------------------------------------------------------------
class NodeState(Base):
    """节点状态（一个流程内每个节点一行）。"""

    __tablename__ = "node_states"
    __table_args__ = (
        UniqueConstraint("flow_id", "node_name", name="uq_node_states_flow_node"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_name: Mapped[str] = mapped_column(String(64), nullable=False)
    node_title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    assignee: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Phase 4 Slice 4D / TIMEOUT-02：证据缺失检测（result_text < 5 字符或显式标记）— PRD §17.2 评分点 #6
    evidence_missing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    flow: Mapped["FlowInstance"] = relationship(back_populates="nodes")
    actions: Mapped[list["ActionLog"]] = relationship(
        back_populates="node_state", cascade="all, delete-orphan", lazy="noload"
    )


# ---------------------------------------------------------------------------
# 3. action_logs —— 动作日志 append-only
# ---------------------------------------------------------------------------
class ActionLog(Base):
    """动作日志（每次决策 / 系统事件一行）。"""

    __tablename__ = "action_logs"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_state_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.node_states.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    actor: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'success'")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    flow: Mapped["FlowInstance"] = relationship(back_populates="actions")
    node_state: Mapped["NodeState | None"] = relationship(back_populates="actions")


# ---------------------------------------------------------------------------
# 4. users —— 最小用户表（CONTEXT §7）
# ---------------------------------------------------------------------------
class User(Base):
    """用户表（最小集，Phase 4 seed 才大量写入）。"""

    __tablename__ = "users"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manager_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------------------------------------------------------------------------
# 5. notifications —— 通知发送记录（Phase 4 才写入，Phase 1 仅建表）
# ---------------------------------------------------------------------------
class Notification(Base):
    """通知发送记录。"""

    __tablename__ = "notifications"
    __table_args__ = {"schema": "app"}

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_state_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.node_states.id", ondelete="CASCADE"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    body_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ---------------------------------------------------------------------------
# 6. notification_outbox —— 待发送通知队列（Phase 4 写入，Phase 1 仅建表）
# ---------------------------------------------------------------------------
class NotificationOutbox(Base):
    """通知 outbox 表（PRD §5.3 + SUMMARY R5）。

    Phase 4 用：节点函数事务内 INSERT；APScheduler outbox_drain 每 10s drain。
    Phase 1 仅建表 + UNIQUE 约束（防 PITFALLS #16 interrupt 重跑重复入队）。
    """

    __tablename__ = "notification_outbox"
    __table_args__ = (
        UniqueConstraint("flow_id", "node_state_id", "channel", name="uq_outbox_flow_node_channel"),
        {"schema": "app"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_state_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("app.node_states.id", ondelete="CASCADE"),
        nullable=True,
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'pending'"), index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
