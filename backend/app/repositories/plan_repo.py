from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import ProjectPlan
from app.db.models import PlanVersionRow
from app.db.session import db_enabled, get_session

log = logging.getLogger(__name__)


async def save_plan_version(
    revision: int,
    plan: ProjectPlan,
    source: str,
    session: AsyncSession | None = None,
) -> None:
    if not db_enabled():
        return
    payload: dict[str, Any] = plan.model_dump(mode="json")
    row = PlanVersionRow(
        revision=revision,
        tasks_json=payload,
        project_start=plan.project_start,
        source=source,
    )

    async def _do(sess: AsyncSession) -> None:
        sess.add(row)
        await sess.commit()

    if session is not None:
        await _do(session)
    else:
        async with get_session() as sess:
            await _do(sess)
    log.debug("Saved plan_version rev=%s source=%s", revision, source)
