from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PlanVersionRow(Base):
    __tablename__ = "plan_versions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    tasks_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    project_start: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatTurnRow(Base):
    __tablename__ = "chat_turns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    command_batch: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    applied: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_changed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_revision_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_revision_after: Mapped[int | None] = mapped_column(Integer, nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    exemplars: Mapped[list[ExemplarRow]] = relationship(
        "ExemplarRow", back_populates="chat_turn", cascade="all, delete-orphan"
    )


class ExemplarRow(Base):
    __tablename__ = "exemplars"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    chat_turn_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("chat_turns.id", ondelete="CASCADE"), nullable=False
    )
    user_message_norm: Mapped[str] = mapped_column(Text, nullable=False)
    plan_signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    command_template: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chat_turn: Mapped[ChatTurnRow] = relationship("ChatTurnRow", back_populates="exemplars")
