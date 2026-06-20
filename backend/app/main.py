import asyncio
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

from app.api import files, history, jobs, settings, sse, triggers, watch_folders, webhooks
from app.core.config import app_settings
from app.core.security import ApiError
from app.core.database import AsyncSessionLocal
from app.models.orm import Settings
from app.services.watcher import Watcher, WatcherService

logger = logging.getLogger(__name__)

_API_V1_PREFIX = "/api/v1"


async def _enqueue_detected_path(path: str) -> None:
    """Async consumer for paths emitted by the watchdog thread.

    Inserts a Job row with `source="watch_folder"` (the
    JobRow renders an orange Auto badge for these), then dispatches the
    Celery task. Defaults pulled from settings; target language falls back
    to `en` since the model has no per-app default field yet.
    """
    from app.models.schemas import JobCreate
    from app.services import job_service

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT * FROM settings WHERE id = 1"))
        row = result.mappings().first()
        if row is None:
            logger.warning("Watcher: no settings row, dropping detected file %s", path)
            return
        payload = JobCreate(
            file_path=path,
            language=row.get("default_target_language") or "en",
            translate=False,
            source="watch_folder",
        )
        job = await job_service.enqueue_job(session, payload)

    logger.info("Auto-enqueued watch-folder job: %s (id=%s)", path, job.id)


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

    # start the watchdog observer over the configured paths.
    # The handler runs in watchdog's thread; we trampoline detected paths
    # back onto the FastAPI event loop via run_coroutine_threadsafe.
    main_loop = asyncio.get_running_loop()

    def _on_detected(path: str) -> None:
        # Called from the watchdog thread. Schedule the async enqueue on
        # the main loop and don't block — the observer must keep ticking.
        asyncio.run_coroutine_threadsafe(_enqueue_detected_path(path), main_loop)

    watcher = WatcherService(_on_detected)
    app.state.watcher = watcher
    # watcher.start() moved to triggers-table-based bootstrap

    # Automations V1 — trigger-table Watcher. Without it, UI-created watch
    # triggers never fire (the producer side of the Automations feature).
    trigger_watcher = Watcher()
    await trigger_watcher.start()
    app.state.trigger_watcher = trigger_watcher

    try:
        yield
    finally:
        # Each stop runs independently so one failure doesn't shadow the other.
        try:
            watcher.stop()
        except Exception:
            logger.exception("legacy WatcherService stop failed")
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
