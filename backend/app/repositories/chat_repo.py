from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatTurnRow
from app.db.session import db_enabled, get_session

log = logging.getLogger(__name__)


async def save_chat_turn(
    *,
    user_message: str,
    summary: str | None,
    command_batch: dict[str, Any],
    applied: int,
    plan_changed: bool,
    reason: str,
    provider: str | None,
    llm_latency_ms: int | None,
    plan_revision_before: int | None,
    plan_revision_after: int | None,
    provenance: str | None,
    session: AsyncSession | None = None,
) -> int | None:
    if not db_enabled():
        return None
    row = ChatTurnRow(
        user_message=user_message,
        summary=summary,
        command_batch=command_batch,
        applied=applied,
        plan_changed=plan_changed,
        reason=reason,
        provider=provider,
        llm_latency_ms=llm_latency_ms,
        plan_revision_before=plan_revision_before,
        plan_revision_after=plan_revision_after,
        provenance=provenance,
    )

    async def _do(sess: AsyncSession) -> int:
        sess.add(row)
        await sess.flush()
        tid = int(row.id)
        await sess.commit()
        return tid

    if session is not None:
        return await _do(session)
    async with get_session() as sess:
        tid = await _do(sess)
    log.debug("Saved chat_turn id=%s reason=%s", tid, reason)
    return tid
