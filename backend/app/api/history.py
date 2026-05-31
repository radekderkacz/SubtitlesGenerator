"""History API and Log API.

Three endpoints under ``/api/v1/history``:

* ``GET    /api/v1/history``                — list terminal jobs (optional ?status filter)
* ``GET    /api/v1/history/{id}/log``       — return the per-job log file
* ``DELETE /api/v1/history``                — purge every terminal job
"""
import os
import uuid
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.orm import Job
from app.models.schemas import HistoryDeleteResponse, HistoryResponse
from app.services import job_service

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]
TerminalStatus = Literal["completed", "failed", "cancelled"]

_DEFAULT_LOG_DIR = "./data/logs"


def resolve_history_model(job: Job) -> Optional[str]:
    """Return the transcription model name to render in History's 'Model' column.

    SP-2 moved the canonical source of per-job backend config from the legacy
    ORM columns (``model_size``, ``translation_provider`` …) into a
    ``backend_profile`` JSON snapshot captured at submission time, and
    `enqueue_job` no longer populates ``model_size``. Reading the legacy
    column directly therefore shows ``None`` (blank) for every post-SP-2 job.

    Resolution order:
        1. ``backend_profile.transcription_model`` — set by remote-api jobs
           (e.g. ``"large-v3"`` from the chosen profile).
        2. ``backend_profile.whisper_model``       — historical fallback for
           jobs submitted before the local-WhisperX backend was removed
           (May 2026). Kept as a read so old rows still render.
        3. ``job.model_size``                      — pre-SP-2 fallback.

    Centralised so any future History-shaped response (watch-folder
    activity feed, JobResponse, etc.) reads through one resolver — closes
    the drift seam the SP-2 refactor opened (see
    ``feedback_holistic_review_seam_bugs`` memory).
    """
    profile = job.backend_profile or {}
    return (
        profile.get("transcription_model")
        or profile.get("whisper_model")
        or job.model_size
    )


def _output_srt_path(file_path: str, target_language: Optional[str]) -> Optional[str]:
    """Mirror ``app.worker.tasks._output_srt_path``.

    Returns ``None`` for jobs that never picked a target language (e.g. failed
    pre-extraction) so the frontend can fall back to a "no SRT" treatment
    without rendering a misleading filename.
    """
    if not target_language:
        return None
    base, _ext = os.path.splitext(file_path)
    return f"{base}.{target_language}.srt"


def _to_history_response(job: Job) -> HistoryResponse:
    return HistoryResponse(
        id=job.id,
        status=job.status,
        file_path=job.file_path,
        source_language=job.source_language,
        target_language=job.target_language,
        model_size=resolve_history_model(job),
        translation_provider=job.translation_provider,
        translation_model=job.translation_model,
        prompt_tokens=job.prompt_tokens,
        completion_tokens=job.completion_tokens,
        total_tokens=job.total_tokens,
        cost_usd=job.cost_usd,
        srt_path=_output_srt_path(job.file_path, job.target_language),
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        jellyfin_refreshed_at=job.jellyfin_refreshed_at,
    )


def _safe_log_path(validated_id: uuid.UUID) -> str:
    """Build the log file path from a known-trusted UUID and the configured
    log directory.

    The URL ``job_id`` is parsed as a UUID before this function is called,
    so the only string that reaches the filesystem here is the canonical
    UUID form (e.g. ``11111111-2222-3333-4444-555555555555``). No
    user-controlled data flows into the path — the URL parameter is
    discarded after validation, the basename is reconstructed from
    ``str(validated_id)`` (CWE-22 sanitisation, Snyk path-traversal).
    """
    base = os.environ.get("SUBGEN_LOG_DIR", _DEFAULT_LOG_DIR)
    return os.path.join(base, f"{validated_id}.log")


StatusFilter = Annotated[Optional[TerminalStatus], Query()]


@router.get(
    "/history",
    responses={
        200: {"description": "Terminal jobs ordered by created_at desc"},
        422: {"description": "status filter is not a terminal status"},
    },
)
async def list_history(
    session: DbSession,
    status: StatusFilter = None,
) -> list[HistoryResponse]:
    rows = await job_service.list_history(session, status_filter=status)
    return [_to_history_response(j) for j in rows]


@router.get(
    "/history/{job_id}/log",
    responses={
        200: {"description": "Plain-text log content"},
        404: {"description": "Job or log file not found"},
    },
)
async def get_history_log(job_id: str, session: DbSession) -> Response:
    # Parse the URL parameter as a UUID *before* it touches anything else.
    # This rejects path-traversal payloads (`../etc/passwd`), bare strings,
    # and anything else that doesn't fit the format. After this point the
    # URL value is discarded; the path is built from the canonical UUID
    # form via `_safe_log_path` (CWE-22 sanitisation).
    try:
        validated_id = uuid.UUID(job_id)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=404,
            content={"detail": "Job not found", "code": "JOB_NOT_FOUND"},
        )

    job = await job_service.get_job(session, str(validated_id))
    if job is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "Job not found", "code": "JOB_NOT_FOUND"},
        )
    log_path = _safe_log_path(validated_id)
    if not os.path.isfile(log_path):
        return JSONResponse(
            status_code=404,
            content={"detail": "Log not found", "code": "LOG_NOT_FOUND"},
        )
    return FileResponse(path=log_path, media_type="text/plain")


@router.delete(
    "/history",
    responses={200: {"description": "Number of terminal jobs deleted"}},
)
async def delete_history(session: DbSession) -> HistoryDeleteResponse:
    deleted = await job_service.delete_terminal_jobs(session)
    return HistoryDeleteResponse(deleted=deleted)
