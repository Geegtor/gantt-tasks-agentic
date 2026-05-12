from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.db.base import Base

log = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, echo=False, pool_pre_ping=True)


async def init_db() -> None:
    global _engine, _session_factory
    s = get_settings()
    url = (s.database_url or "").strip()
    if not url:
        log.info("DATABASE_URL empty — persistence disabled")
        _engine = None
        _session_factory = None
        return
    if _engine is not None:
        return
    _engine = _make_engine(url)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    if s.run_migrations_on_start:
        await _run_alembic_upgrade()
    else:
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    log.info("Database initialized")


async def _run_alembic_upgrade() -> None:
    """Run Alembic migrations in a thread (blocking Alembic API)."""
    import asyncio
    import os
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    ini = backend_root / "alembic.ini"
    if not ini.exists():
        log.warning("alembic.ini not found — using create_all")
        assert _engine is not None
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        return

    def _upgrade() -> None:
        prev = os.getcwd()
        try:
            os.chdir(backend_root)
            cfg = Config(str(ini))
            cfg.set_main_option("script_location", str(backend_root / "alembic"))
            command.upgrade(cfg, "head")
        finally:
            os.chdir(prev)

    await asyncio.to_thread(_upgrade)


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def db_enabled() -> bool:
    return _session_factory is not None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("Database not configured")
    async with _session_factory() as session:
        yield session
