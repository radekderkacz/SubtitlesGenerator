import uuid

from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Job, Settings, _utcnow
from app.models.schemas import JobCreate, JobStatus

_ACTIVE_STATUSES: tuple[JobStatus, ...] = (JobStatus.queued, JobStatus.processing)
_TERMINAL_STATUSES: tuple[JobStatus, ...] = (
    JobStatus.completed,
    JobStatus.failed,
    JobStatus.cancelled,
)


class ProfileNotFoundError(Exception):
    """Raised by enqueue_job when JobCreate.profile_name is not in
    Settings.profiles. The API layer maps this to a 422."""


class DuplicateJobError(Exception):
    """An active (queued/processing) job already exists for this file. Raised
    on the pre-check or when the uq_jobs_active_file partial unique index
    rejects the insert (the backstop for check-then-act races). The API layer
    maps this to a 409."""

    def __init__(self, file_path: str) -> None:
        super().__init__(f"An active job already exists for {file_path}")
        self.file_path = file_path


async def _commit_new_job(session: AsyncSession, job: Job) -> Job:
    """Commit a new Job row, translating a unique-index rejection into
    DuplicateJobError (with rollback so the session stays usable)."""
    session.add(job)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicateJobError(job.file_path) from exc
    await session.refresh(job)
    return job


async def enqueue_job(
    session: AsyncSession, payload: JobCreate, *, dispatch: bool = True
) -> Job:
    """Insert a new Job row AND (by default) dispatch the Celery task.

    Atomic chokepoint: callers cannot forget step 2. The dispatch happens
    AFTER commit, so if the row insert raises (e.g. ProfileNotFoundError)
    no Celery task is ever enqueued.

    Pass ``dispatch=False`` if you need to mutate the job row after the
    insert but before the worker can race ahead — then call
    ``generate_subtitles.delay(job.id)`` manually after your final commit.
    """
    now = _utcnow()
    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings_row = result.scalar_one_or_none()
    profiles = (settings_row.profiles or []) if settings_row else []
    profile = next((p for p in profiles if p.get("name") == payload.profile_name), None)
    if profile is None:
        raise ProfileNotFoundError(payload.profile_name)
    # settings_row is guaranteed non-None past this point: a missing
    # settings row → empty profiles → ProfileNotFoundError above.

    backend_keys = (
        "transcription_backend", "transcription_api_url", "transcription_model",
        "transcription_api_key", "translation_provider", "translation_model",
        "translation_api_url", "translation_api_key",
    )
    snapshot = {k: profile.get(k) for k in backend_keys}
    snapshot["name"] = profile.get("name")

    if await _has_active_job_for_path(session, payload.file_path):
        raise DuplicateJobError(payload.file_path)

    job = Job(
        id=str(uuid.uuid4()),
        file_path=payload.file_path,
        source_language=payload.source_language,
        target_language=payload.target_language if payload.translate else None,
        backend_profile=snapshot,
        source=payload.source or "manual",
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
    )
    job = await _commit_new_job(session, job)

    if dispatch:
        # Deferred import: worker.tasks pulls in Celery + ffmpeg + whisperx and
        # would create a heavy circular import at module load. This call is
        # what made the Automations watch trigger work end-to-end — before it
        # was here, dispatch_event created queued rows that no worker ever
        # saw (Celery broker was empty, jobs sat forever).
        from app.worker.tasks import generate_subtitles
        generate_subtitles.delay(job.id)

    return job


async def get_job(session: AsyncSession, job_id: str) -> Job | None:
    return await session.get(Job, job_id)


async def list_jobs(session: AsyncSession) -> list[Job]:
    result = await session.execute(select(Job).order_by(desc(Job.created_at)))
    return result.scalars().all()


async def cancel_job(session: AsyncSession, job_id: str) -> Job:
    """Mark an existing job cancelled. Caller must have verified the row exists."""
    job = await session.get(Job, job_id)
    assert job is not None, "cancel_job called on missing row — caller must check first"
    job.status = JobStatus.cancelled
    job.updated_at = _utcnow()
    await session.commit()
    await session.refresh(job)
    return job


async def delete_job(session: AsyncSession, job_id: str) -> bool:
    """Hard-delete a job row. Returns True on success, False if not found."""
    job = await session.get(Job, job_id)
    if job is None:
        return False
    await session.delete(job)
    await session.commit()
    return True


class RetryError(Exception):
    """Raised by ``retry_failed_job`` for non-retryable source jobs.
    The API layer translates this to a 404 / 400."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# A job that's been ``queued`` longer than this without transitioning to
# ``processing`` is treated as an orphan — most likely the API created the
# DB row but the corresponding Celery dispatch was lost (incident
# 2026-05-15). Below the threshold the row is just waiting for the worker
# to pick it up (or sitting out a scheduled auto-retry backoff — up to
# 900s, tasks._JOB_RETRY_BACKOFF); inviting a manual retry inside that
# window double-ran jobs (2026-07 audit R6).
STUCK_QUEUED_THRESHOLD_SECONDS = 1200


async def _clone_and_queue(session: AsyncSession, original: Job) -> Job:
    """Create a fresh queued Job copying the original's file + settings snapshot.
    ``backend_profile`` is the single source of truth for the worker, so the new
    run is identical to the original's configuration."""
    now = _utcnow()
    new_job = Job(
        id=str(uuid.uuid4()),
        file_path=original.file_path,
        source_language=original.source_language,
        target_language=original.target_language,
        backend_profile=original.backend_profile,
        source="manual",
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
    )
    return await _commit_new_job(session, new_job)


async def retry_failed_job(
    session: AsyncSession,
    original_id: str,
) -> Job:
    """Re-queue a failed or stale-queued job, copying the original's
    ``backend_profile`` snapshot so the retried run is identical to the
    original attempt.

    The ``backend_profile`` (set at submission time) is the single source of
    truth for which engine/model/provider the worker uses — no Settings row is
    consulted here. Legacy columns (``model_size``, ``translation_provider``,
    ``translation_model``) are left unset on the new job; they are no longer
    the config source.

    A job in ``status=queued`` is also retryable, but only after
    ``STUCK_QUEUED_THRESHOLD_SECONDS`` have elapsed since its ``updated_at``
    — the orphan-queued recovery path. Below that threshold the row is
    treated as still-being-picked-up and the call rejects with
    ``JOB_QUEUED_TOO_FRESH`` so the UI can show a "wait a few seconds"
    message instead of inviting double-submission.
    """
    original = await session.get(Job, original_id)
    if original is None:
        raise RetryError("JOB_NOT_FOUND", "Job not found")
    if original.status == JobStatus.queued:
        age = (_utcnow() - original.updated_at).total_seconds()
        if age < STUCK_QUEUED_THRESHOLD_SECONDS:
            raise RetryError(
                "JOB_QUEUED_TOO_FRESH",
                f"Job is queued but only {int(age)}s old — wait at least "
                f"{STUCK_QUEUED_THRESHOLD_SECONDS}s before retrying",
            )
        # Stale-queued falls through to the retry path.
    elif original.status != JobStatus.failed:
        raise RetryError(
            "JOB_NOT_FAILED",
            f"Only failed jobs can be retried (got status={original.status})",
        )

    return await _clone_and_queue(session, original)


async def _has_active_job_for_path(session: AsyncSession, file_path: str) -> bool:
    result = await session.execute(
        select(Job.id)
        .where(Job.file_path == file_path, Job.status.in_(_ACTIVE_STATUSES))
        .limit(1)
    )
    return result.first() is not None


class RegenerateError(Exception):
    """Raised by ``regenerate_job``. The API maps the code to 404 / 400 / 409."""
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


async def regenerate_job(session: AsyncSession, original_id: str) -> Job:
    """Re-queue a terminal job's file using its original settings snapshot.
    Refuses non-terminal source jobs and duplicates (an active job already exists
    for the same file)."""
    original = await session.get(Job, original_id)
    if original is None:
        raise RegenerateError("JOB_NOT_FOUND", "Job not found")
    if original.status not in _TERMINAL_STATUSES:
        raise RegenerateError(
            "JOB_NOT_TERMINAL",
            f"Only finished jobs can be regenerated (got status={original.status})",
        )
    if await _has_active_job_for_path(session, original.file_path):
        raise RegenerateError("ALREADY_ACTIVE", "A job for this file is already in the queue")
    return await _clone_and_queue(session, original)


async def list_history(
    session: AsyncSession, status_filter: str | None = None
) -> list[Job]:
    """Terminal jobs (completed / failed / cancelled), newest first.

    When ``status_filter`` is provided it must be one of the terminal statuses;
    callers (the API layer) are responsible for validating it.
    """
    statuses: tuple[JobStatus | str, ...] = (
        (status_filter,) if status_filter is not None else _TERMINAL_STATUSES
    )
    result = await session.execute(
        select(Job).where(Job.status.in_(statuses)).order_by(desc(Job.created_at))
    )
    return result.scalars().all()


async def delete_terminal_jobs(session: AsyncSession) -> int:
    """Hard-delete every completed/failed/cancelled row. Returns the count."""
    result = await session.execute(
        delete(Job).where(Job.status.in_(_TERMINAL_STATUSES))
    )
    await session.commit()
    return result.rowcount or 0


async def cancel_all_active(session: AsyncSession) -> list[Job]:
    """Mark every queued+processing job as cancelled. Returns the updated list."""
    result = await session.execute(
        select(Job).where(Job.status.in_(_ACTIVE_STATUSES))
    )
    jobs = result.scalars().all()
    if not jobs:
        return []
    now = _utcnow()
    for job in jobs:
        job.status = JobStatus.cancelled
        job.updated_at = now
    await session.commit()
    # Rows are already in the identity map with the new status/updated_at,
    # so we skip the per-row refresh round-trips.
    return jobs
