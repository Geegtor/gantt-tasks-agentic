from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.command_template import cosine_similarity
from app.db.models import ExemplarRow
from app.db.session import db_enabled, get_session

log = logging.getLogger(__name__)


@dataclass
class ExemplarHit:
    id: int
    plan_signature: str
    user_message_norm: str
    command_template: dict
    embedding: list[float] | None
    similarity: float


async def search_exemplars(
    *,
    query_embedding: list[float] | None,
    plan_signature: str,
    limit: int = 5,
    session: AsyncSession | None = None,
) -> list[ExemplarHit]:
    if not db_enabled():
        return []

    async def _do(sess: AsyncSession) -> list[ExemplarHit]:
        q = (
            select(ExemplarRow)
            .where(ExemplarRow.plan_signature == plan_signature)
            .order_by(ExemplarRow.created_at.desc())
            .limit(80)
        )
        res = await sess.execute(q)
        rows = list(res.scalars().all())
        hits: list[ExemplarHit] = []
        for r in rows:
            emb = list(r.embedding) if r.embedding is not None else None
            sim = 0.0
            if query_embedding and emb and len(query_embedding) == len(emb):
                sim = cosine_similarity(query_embedding, emb)
            else:
                sim = 0.0
            hits.append(
                ExemplarHit(
                    id=int(r.id),
                    plan_signature=r.plan_signature,
                    user_message_norm=r.user_message_norm,
                    command_template=dict(r.command_template),
                    embedding=emb,
                    similarity=sim,
                )
            )
        hits.sort(key=lambda h: (h.similarity, h.id), reverse=True)
        return hits[:limit]

    if session is not None:
        return await _do(session)
    async with get_session() as sess:
        return await _do(sess)


async def insert_exemplar(
    *,
    chat_turn_id: int,
    user_message_norm: str,
    plan_signature: str,
    command_template: dict,
    embedding: list[float] | None,
    session: AsyncSession | None = None,
) -> None:
    if not db_enabled():
        return

    row = ExemplarRow(
        chat_turn_id=chat_turn_id,
        user_message_norm=user_message_norm,
        plan_signature=plan_signature,
        command_template=command_template,
        embedding=embedding,
        schema_version=1,
    )

    async def _do(sess: AsyncSession) -> None:
        sess.add(row)
        await sess.commit()

    if session is not None:
        await _do(session)
    else:
        async with get_session() as sess:
            await _do(sess)
    log.debug("Inserted exemplar for chat_turn_id=%s", chat_turn_id)
