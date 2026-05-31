from typing import Annotated

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import _is_system_configured
from app.core.database import get_db
from app.core.security import validate_nas_path
from app.models.orm import Settings
from app.models.schemas import (
    JobCreate,
    JobResponse,
    JobStatus,
    JobSubmitResponse,
)
from app.services import job_service
from app.services.job_events import publish_job_update, publish_job_updates
from app.worker.tasks import generate_subtitles

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]

_JOB_NOT_FOUND_DETAIL = "Job not found"
_JOB_NOT_FOUND_CODE = "JOB_NOT_FOUND"


@router.post(
    "/jobs",
    status_code=202,
    response_model=JobSubmitResponse,
    responses={
        400: {"description": "Path outside NAS mount"},
        422: {"description": "System not configured"},
    },
)
async def create_job(payload: JobCreate, session: DbSession):
    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings_row = result.scalar_one_or_none()
    if settings_row is None or not _is_system_configured(settings_row):
        return JSONResponse(
            status_code=422,
            content={"detail": "System not configured. Complete settings setup first.", "code": "NOT_CONFIGURED"},
        )
    validate_nas_path(payload.file_path, settings_row.nas_mount_path)
    try:
        # enqueue_job is atomic — DB insert + Celery dispatch in one call.
        job = await job_service.enqueue_job(session, payload)
    except job_service.ProfileNotFoundError as e:
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"AI profile '{e}' not found — create it in Settings → Profiles.",
                "code": "PROFILE_NOT_FOUND",
            },
        )
    return job


@router.get(
    "/jobs",
    response_model=list[JobResponse],
    responses={200: {"description": "Job list ordered by created_at desc"}},
)
async def list_jobs(session: DbSession):
    return await job_service.list_jobs(session)


@router.get(
    "/jobs/{job_id}",
    response_model=JobResponse,
    responses={404: {"description": "Job not found"}},
)
async def get_job(job_id: str, session: DbSession):
    job = await job_service.get_job(session, job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": _JOB_NOT_FOUND_DETAIL, "code": _JOB_NOT_FOUND_CODE},
        )
    return job


@router.post(
    "/jobs/stop-all",
    response_model=list[JobResponse],
    responses={200: {"description": "List of jobs that transitioned to cancelled"}},
)
async def stop_all_jobs(session: DbSession):
    cancelled = await job_service.cancel_all_active(session)
    await publish_job_updates(cancelled)
    return cancelled


@router.post(
    "/jobs/{job_id}/retry",
    status_code=202,
    response_model=JobSubmitResponse,
    responses={
        400: {"description": "Source job is not in a retryable state (or queued too briefly)"},
        404: {"description": "Source job not found"},
        422: {"description": "Settings not configured"},
    },
)
async def retry_job(job_id: str, session: DbSession):
    """Re-queue a failed or stale-queued job using the **current** Settings
    configuration.

    The user's original model/provider choices are intentionally not honoured —
    a retry always uses whatever is currently in Settings.
    A queued job is retryable once it's been queued longer than
    ``STUCK_QUEUED_THRESHOLD_SECONDS`` — that recovers the orphan-queued
    pattern (DB row inserted, Celery task lost on worker corruption).
    """
    try:
        new_job = await job_service.retry_failed_job(session, job_id)
    except job_service.RetryError as e:
        if e.code == "JOB_NOT_FOUND":
            status = 404
        elif e.code == "SETTINGS_NOT_CONFIGURED":
            status = 422
        else:
            # 400 covers JOB_NOT_FAILED + JOB_QUEUED_TOO_FRESH. The frontend
            # discriminates by `code` to choose between "this job can't be
            # retried" and "wait a few more seconds".
            status = 400
        return JSONResponse(
            status_code=status,
            content={"detail": str(e), "code": e.code},
        )
    generate_subtitles.delay(new_job.id)
    return new_job


@router.post(
    "/jobs/{job_id}/jellyfin-refresh",
    response_model=JobResponse,
    responses={
        200: {"description": "Refresh triggered, jellyfin_refreshed_at stamped"},
        404: {"description": "Job not found"},
        409: {"description": "Job is not in a state where Jellyfin refresh applies"},
        422: {"description": "Jellyfin is not configured in settings"},
        502: {"description": "Jellyfin returned an error or was unreachable"},
    },
)
async def jellyfin_refresh(job_id: str, session: DbSession):
    from app.models.orm import _utcnow
    from app.services.jellyfin import (
        JellyfinNotConfigured,
        JellyfinRefreshError,
        trigger_library_scan,
    )

    job = await job_service.get_job(session, job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": _JOB_NOT_FOUND_DETAIL, "code": _JOB_NOT_FOUND_CODE},
        )
    if job.status != JobStatus.completed:
        return JSONResponse(
            status_code=409,
            content={
                "detail": "Jellyfin refresh applies only to completed jobs",
                "code": "JOB_NOT_COMPLETED",
            },
        )

    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        return JSONResponse(
            status_code=422,
            content={"detail": "Settings not found", "code": "SETTINGS_NOT_FOUND"},
        )

    try:
        await trigger_library_scan(settings)
    except JellyfinNotConfigured:
        return JSONResponse(
            status_code=422,
            content={"detail": "Jellyfin is not configured", "code": "JELLYFIN_NOT_CONFIGURED"},
        )
    except JellyfinRefreshError as e:
        return JSONResponse(
            status_code=502,
            content={"detail": str(e), "code": "JELLYFIN_REFRESH_FAILED"},
        )

    job.jellyfin_refreshed_at = _utcnow()
    await session.commit()
    await session.refresh(job)
    await publish_job_update(job)
    return JobResponse.model_validate(job, from_attributes=True)


@router.delete(
    "/jobs/{job_id}",
    responses={
        200: {"description": "Processing job cancelled (status=cancelled)"},
        204: {"description": "Queued or terminal job hard-deleted"},
        404: {"description": "Job not found"},
    },
)
async def delete_job(job_id: str, session: DbSession):
    job = await job_service.get_job(session, job_id)
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": _JOB_NOT_FOUND_DETAIL, "code": _JOB_NOT_FOUND_CODE},
        )
    if job.status == JobStatus.processing:
        cancelled = await job_service.cancel_job(session, job_id)
        await publish_job_update(cancelled)
        return JobResponse.model_validate(cancelled, from_attributes=True)
    # queued / completed / failed / cancelled → hard delete
    await job_service.delete_job(session, job_id)
    return Response(status_code=204)
