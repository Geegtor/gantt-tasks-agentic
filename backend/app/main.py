from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request

from app.api.chat import router as chat_router
from app.api.tasks import router as tasks_router
from app.api.ws import router as ws_router
from app.config import get_settings
from app.db.session import close_db, init_db

log = logging.getLogger(__name__)

# Import-time bootstrap (covers MCP-mount and other module-level logs).
# Do not use force=True: it clears the root logger and can fight uvicorn
# ``--log-config`` / dictConfig ordering.
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

_LOG_FMT = logging.Formatter(
    "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)


class _HealthFilter(logging.Filter):
    """Drop successful /health access log lines to reduce noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not ('"GET /health' in msg and " 200" in msg)


def _stdout_handler() -> logging.StreamHandler:
    """New handler per logger; sharing one StreamHandler across loggers is discouraged."""
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(_LOG_FMT)
    return h


def _configure_app_logging() -> None:
    """Re-attach handlers AFTER uvicorn's dictConfig has run.

    Also run after Alembic ``fileConfig(alembic.ini)``: that path calls
    ``logging.config._clearExistingHandlers()`` and can leave pre-existing
    loggers disabled or with dead handler objects unless we re-apply here.

    Called from lifespan (after ``init_db``) and at import after
    ``create_app()`` for early messages.
    """
    # Re-anchor root so third-party loggers (httpx, sqlalchemy, etc.)
    # always have a visible handler.
    root = logging.getLogger()
    root.handlers = [_stdout_handler()]
    root.setLevel(logging.INFO)

    # Point uvicorn's own loggers at stdout too (they default to stderr).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers = [_stdout_handler()]
        uv_logger.setLevel(logging.INFO)
        uv_logger.propagate = False

    for name in ("app", "alembic"):
        logger = logging.getLogger(name)
        logger.handlers = [_stdout_handler()]
        logger.setLevel(logging.INFO)
        logger.propagate = False  # don't double-log via root

    # Uvicorn caches access_log = uvicorn.access.hasHandlers() per connection.
    # If access had no handlers and propagate=False, access lines never emit.
    access = logging.getLogger("uvicorn.access")
    if not access.handlers:
        access.handlers = [_stdout_handler()]
        access.setLevel(logging.INFO)
        access.propagate = False
    if not any(isinstance(f, _HealthFilter) for f in access.filters):
        access.addFilter(_HealthFilter())

    # Re-enable app subtree after Alembic fileConfig may have set disabled=True.
    for name in list(logging.Logger.manager.loggerDict.keys()):
        if not isinstance(name, str) or not (name == "app" or name.startswith("app.")):
            continue
        lg = logging.getLogger(name)
        if isinstance(lg, logging.Logger):
            lg.disabled = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    _configure_app_logging()
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Gantt AI Backend", lifespan=lifespan)
    origins = [o.strip() for o in settings.cors_origin.split(",") if o.strip()]
    if not origins:
        origins = ["http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tasks_router)
    app.include_router(chat_router)
    app.include_router(ws_router)

    @app.middleware("http")
    async def _log_each_request(request: Request, call_next):
        """Guaranteed request line in Docker even if uvicorn.access was mis-detected."""
        response = await call_next(request)
        if request.url.path == "/health" and response.status_code == 200:
            return response
        logging.getLogger("app.http").info(
            "%s %s -> %s",
            request.method,
            request.url.path,
            response.status_code,
        )
        return response

    @app.get("/health")
    def health():
        return {"ok": True}

    try:
        from app.mcp_server import streamable_http_asgi

        app.mount("/mcp", streamable_http_asgi())
        log.info("MCP mounted at /mcp")
    except Exception as e:
        log.warning("MCP mount skipped (%s). REST and WebSocket still work.", e)

    return app


app = create_app()
# Run once at import so logs work before lifespan (and after uvicorn dictConfig).
_configure_app_logging()
