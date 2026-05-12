from __future__ import annotations

import logging

from app.core.state import session
from app.repositories import plan_repo

log = logging.getLogger(__name__)


async def persist_current_plan(source: str) -> None:
    """Write current session plan to DB (no-op if DATABASE_URL unset)."""
    try:
        await plan_repo.save_plan_version(session.revision, session.plan, source)
    except Exception as e:
        log.warning("persist_current_plan failed: %s", e)
