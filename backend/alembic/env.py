from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure backend root is on path (alembic invoked from backend/)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    # Default disable_existing_loggers=True turns off every logger already
    # registered (e.g. app.api.*) except those listed in alembic.ini — breaks
    # FastAPI app logging after migrations.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_sync_url() -> str:
    s = get_settings()
    url = (s.database_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for migrations")
    if "+asyncpg" in url:
        return url.replace("postgresql+asyncpg", "postgresql+psycopg", 1)
    return url


def run_migrations_offline() -> None:
    url = get_sync_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_sync_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
