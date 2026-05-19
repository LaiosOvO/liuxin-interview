"""Meeting v1: persistence + RAG 检索源

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-18

变更摘要：
- 新增 `app.meetings` 表：存原始会议纪要文本 + AI 提炼摘要 + extract JSON +
  原始来源 URL（飞书 docx / wiki）+ AI 生成的飞书文档 URL
- 用途：pageindex 风格 RAG —— bot @ 提问时不再依赖飞书 list_files API（权限阻塞），
  而是从 DB 检索（title + summary 给 LLM 做 router，content 拉回答）
- 索引：ingested_at DESC + chat_id（场景化检索）
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "meetings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column(
            "extract_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("source_url", sa.Text, nullable=True, comment="来源飞书 doc/wiki URL"),
        sa.Column("ai_doc_url", sa.Text, nullable=True, comment="AI 总结写到的飞书文档 URL"),
        sa.Column("ingested_by", sa.String(length=128), nullable=True),
        sa.Column("chat_id", sa.String(length=128), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="app",
    )
    op.create_index(
        "ix_meetings_ingested_at",
        "meetings",
        [sa.text("ingested_at DESC")],
        schema="app",
    )
    op.create_index(
        "ix_meetings_chat_id",
        "meetings",
        ["chat_id"],
        schema="app",
    )


def downgrade() -> None:
    op.drop_index("ix_meetings_chat_id", table_name="meetings", schema="app")
    op.drop_index("ix_meetings_ingested_at", table_name="meetings", schema="app")
    op.drop_table("meetings", schema="app")
