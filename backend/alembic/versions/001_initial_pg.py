"""initial plan_versions chat_turns exemplars

Revision ID: 001_initial
Revises:
Create Date: 2026-05-10

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_versions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("tasks_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("project_start", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "chat_turns",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_message", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("command_batch", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("applied", sa.Integer(), nullable=False),
        sa.Column("plan_changed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("plan_revision_before", sa.Integer(), nullable=True),
        sa.Column("plan_revision_after", sa.Integer(), nullable=True),
        sa.Column("provenance", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_turns_created_at", "chat_turns", ["created_at"], unique=False)
    op.create_table(
        "exemplars",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("chat_turn_id", sa.BigInteger(), nullable=False),
        sa.Column("user_message_norm", sa.Text(), nullable=False),
        sa.Column("plan_signature", sa.String(length=64), nullable=False),
        sa.Column("command_template", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("embedding", postgresql.ARRAY(sa.Float()), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["chat_turn_id"], ["chat_turns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_exemplars_plan_signature", "exemplars", ["plan_signature"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_exemplars_plan_signature", table_name="exemplars")
    op.drop_table("exemplars")
    op.drop_index("ix_chat_turns_created_at", table_name="chat_turns")
    op.drop_table("chat_turns")
    op.drop_table("plan_versions")
