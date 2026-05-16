"""Phase 4 Slice 4D: add node_states.evidence_missing

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-16

变更摘要：
1. node_states 加 `evidence_missing` Boolean 列（PRD §17.2 / TIMEOUT-02 评分点 #6）
   - 默认 false；result_text 长度 < 5 字符时由检测 helper 标 true
   - 显式标记由 Mattermost simulate-evidence-missing 命令置位

注：outbox 唤醒不走 DB 触发器 — 用 in-process asyncio.Event（机制层事件驱动，
   见 workers/outbox_drain.py signal_outbox_pending）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "node_states",
        sa.Column(
            "evidence_missing",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="app",
    )


def downgrade() -> None:
    op.drop_column("node_states", "evidence_missing", schema="app")
