import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api import asr_provider, files, history, jobs, settings, sse, triggers, watch_folders, webhooks
from app.core.config import app_settings
from app.core.security import ApiError
from app.core.database import AsyncSessionLocal
from app.models.orm import Settings
from app.services.watcher import Watcher

logger = logging.getLogger(__name__)

_API_V1_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seed default Settings row (id=1) if not present
    async with AsyncSessionLocal() as session:
        stmt = pg_insert(Settings).values(
            id=1,
            nas_mount_path="/media",
            transcription_backend=None,
        ).on_conflict_do_nothing(index_elements=["id"])
        await session.execute(stmt)
        await session.commit()

    # Legacy Story-8.1 WatcherService wiring removed (2026-07 audit): it was
    # never started, and its enqueue path had drifted from JobCreate (a
    # revival would have crashed). The Automations trigger-table Watcher
    # below is the only file-watching producer.

    # Automations V1 — trigger-table Watcher. Without it, UI-created watch
    # triggers never fire (the producer side of the Automations feature).
    trigger_watcher = Watcher()
    await trigger_watcher.start()
    app.state.trigger_watcher = trigger_watcher

    try:
        yield
    finally:
        try:
            trigger_watcher.stop()
        except Exception:
            logger.exception("trigger Watcher stop failed")


app = FastAPI(title="SubtitlesGenerator", lifespan=lifespan)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "code": exc.code},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = str(uuid.uuid4())
    logger.exception("Unhandled exception [%s]", correlation_id, exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "code": "INTERNAL_ERROR", "correlation_id": correlation_id},
    )


@app.get(
    "/api/v1/health",
    responses={
        200: {"description": "All services healthy"},
        503: {"description": "One or more services degraded"},
    },
)
async def health() -> JSONResponse:
    health_status: dict[str, str] = {"status": "ok", "db": "unknown", "redis": "unknown"}
    http_status = 200

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        health_status["db"] = "ok"
    except Exception:
        health_status["db"] = "error"
        health_status["status"] = "degraded"
        http_status = 503

    try:
        r = aioredis.from_url(app_settings.redis_url)
        try:
            await r.ping()
            health_status["redis"] = "ok"
        finally:
            await r.aclose()
    except Exception:
        health_status["redis"] = "error"
        health_status["status"] = "degraded"
        http_status = 503

    return JSONResponse(status_code=http_status, content=health_status)


app.include_router(settings.router, prefix=_API_V1_PREFIX)
# SSE router must register before jobs.router so /jobs/stream resolves before /jobs/{job_id}
app.include_router(sse.router, prefix=_API_V1_PREFIX)
app.include_router(jobs.router, prefix=_API_V1_PREFIX)
app.include_router(files.router, prefix=_API_V1_PREFIX)
app.include_router(history.router, prefix=_API_V1_PREFIX)
app.include_router(watch_folders.router, prefix=_API_V1_PREFIX)
app.include_router(triggers.router, prefix=_API_V1_PREFIX)
app.include_router(webhooks.router, prefix=_API_V1_PREFIX)
# Bazarr / whisper-asr-webservice protocol lives at the ROOT (no /api/v1):
# Bazarr's whisper provider hardcodes POST /asr and /detect-language.
app.include_router(asr_provider.router)

_STATIC_DIR = Path("/app/static")


def _spa_index_response() -> FileResponse:
    """Serve the SPA entry point with revalidation forced.

    ``index.html`` is the only unhashed file — it references the
    content-hashed ``/assets/*`` bundles by name. Without an explicit
    ``Cache-Control`` the browser may serve a stale ``index.html`` from cache
    and keep pointing at an old bundle until a manual hard-refresh (this is
    why the UI appeared to "lose" recent changes). ``no-cache`` makes the
    browser revalidate on every load — cheap, since it's a 304 via the
    existing etag when unchanged — so a new frontend build is picked up at
    once.
    """
    return FileResponse(
        str(_STATIC_DIR / "index.html"),
        headers={"Cache-Control": "no-cache"},
    )


if _STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        return _spa_index_response()
