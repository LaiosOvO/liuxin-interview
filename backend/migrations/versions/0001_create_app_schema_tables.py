"""create app schema + 6 business tables (Phase 1)

Revision ID: 0001
Revises:
Create Date: 2026-05-16

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 创建 app schema（兼容本地不走 docker init-db.sql 的情况）
    op.execute("CREATE SCHEMA IF NOT EXISTS app")

    # 1. flow_instances
    op.create_table(
        "flow_instances",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("employee_id", sa.String(64), nullable=False),
        sa.Column(
            "template",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'standard_offboarding'"),
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'in_progress'"),
        ),
        sa.Column(
            "context",
            pg.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index(
        "ix_flow_instances_employee_id",
        "flow_instances",
        ["employee_id"],
        schema="app",
    )
    op.create_index("ix_flow_instances_status", "flow_instances", ["status"], schema="app")

    # 2. node_states
    op.create_table(
        "node_states",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "flow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("node_name", sa.String(64), nullable=False),
        sa.Column("node_title", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("assignee", sa.String(64), nullable=True),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column(
            "is_overdue",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("flow_id", "node_name", name="uq_node_states_flow_node"),
        schema="app",
    )
    op.create_index("ix_node_states_flow_id", "node_states", ["flow_id"], schema="app")
    op.create_index("ix_node_states_status", "node_states", ["status"], schema="app")
    op.create_index("ix_node_states_assignee", "node_states", ["assignee"], schema="app")

    # 3. action_logs
    op.create_table(
        "action_logs",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "flow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_state_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.node_states.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("result_text", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'success'"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", pg.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_action_logs_flow_id", "action_logs", ["flow_id"], schema="app")
    op.create_index(
        "ix_action_logs_node_state_id",
        "action_logs",
        ["node_state_id"],
        schema="app",
    )
    op.create_index("ix_action_logs_actor", "action_logs", ["actor"], schema="app")
    op.create_index(
        "ix_action_logs_created_at",
        "action_logs",
        ["created_at"],
        schema="app",
    )

    # 4. users
    op.create_table(
        "users",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=True),
        sa.Column("department", sa.String(64), nullable=True),
        sa.Column("manager_email", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )

    # 5. notifications
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "flow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_state_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.node_states.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(512), nullable=True),
        sa.Column("body_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        schema="app",
    )
    op.create_index("ix_notifications_flow_id", "notifications", ["flow_id"], schema="app")
    op.create_index("ix_notifications_status", "notifications", ["status"], schema="app")

    # 6. notification_outbox
    op.create_table(
        "notification_outbox",
        sa.Column(
            "id",
            pg.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "flow_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.flow_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "node_state_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("app.node_states.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("recipient", sa.String(255), nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "flow_id",
            "node_state_id",
            "channel",
            name="uq_outbox_flow_node_channel",
        ),
        schema="app",
    )
    op.create_index(
        "ix_notification_outbox_flow_id",
        "notification_outbox",
        ["flow_id"],
        schema="app",
    )
    op.create_index(
        "ix_notification_outbox_status",
        "notification_outbox",
        ["status"],
        schema="app",
    )
    op.create_index(
        "ix_notification_outbox_next_attempt_at",
        "notification_outbox",
        ["next_attempt_at"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_table("notification_outbox", schema="app")
    op.drop_table("notifications", schema="app")
    op.drop_table("users", schema="app")
    op.drop_table("action_logs", schema="app")
    op.drop_table("node_states", schema="app")
    op.drop_table("flow_instances", schema="app")
    # 不 drop schema — schema 由 deploy/init-db.sql 创建，alembic 不主动删
