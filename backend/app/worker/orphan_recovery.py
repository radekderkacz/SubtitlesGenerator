"""Worker-startup orphan recovery.

When the worker container is SIGKILLed mid-task (the usual cause: a deploy
exceeding stop_grace_period), the in-flight Celery task is lost. With
`task_acks_late=True` the broker (redis) eventually re-delivers, but only
after `visibility_timeout` expires — default **3600s (1 hour)**. That is far
too long a stall for any user watching the queue.

On worker startup we therefore sweep the DB for jobs left in `processing`
whose `updated_at` is older than `ORPHAN_AGE_SECONDS`. Those jobs cannot
plausibly have a worker actively touching them — every step in the pipeline
updates `updated_at` within seconds. We reset them to `queued` and
re-dispatch via Celery so the freshly-booted worker picks them up
immediately, without waiting on the broker visibility timeout.

This sweep is idempotent: rows older than the cutoff get re-queued; rows
newly transitioned to `processing` by this worker (still within the cutoff)
are skipped.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery.signals import worker_ready
from sqlalchemy import select

logger = logging.getLogger(__name__)

# A processing job that hasn't been touched in this many seconds is treated
# as orphaned. The fastest legitimate phase transition (extracting → end of
# transcribing) writes an update within ~5-10s, so 30s gives ample margin
# while still recovering quickly after a deploy.
# Above the worker's 60s heartbeat (tasks._job_heartbeat) with slack for a
# slow DB write — a live job is never silent longer than ~2 heartbeats.
ORPHAN_AGE_SECONDS = 300


async def _recover_orphans() -> int:
    """Find and re-dispatch orphaned processing jobs. Returns the count."""
    # Imports kept local to avoid pulling SQLAlchemy / ORM into module import
    # time — `worker_ready` fires after Celery has fully bootstrapped, so a
    # lazy import is fine here and keeps `celery_app.py` lean.
    from app.core.database import AsyncSessionLocal
    from app.models.orm import Job
    from app.models.schemas import JobStatus
    from app.worker.tasks import generate_subtitles

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=ORPHAN_AGE_SECONDS)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Job).where(
                Job.status == JobStatus.processing.value,
                Job.updated_at < cutoff,
            )
        )
        orphans = list(result.scalars().all())
        if not orphans:
            return 0
        for job in orphans:
            logger.warning(
                "orphan-recovery: re-queueing job %s (phase=%s progress=%s last_updated=%s)",
                job.id,
                job.phase,
                job.progress,
                job.updated_at.isoformat(),
            )
            job.status = JobStatus.queued.value
            job.phase = None
            job.progress = 0
            job.error_message = "Auto-recovered after worker restart"
        await session.commit()
        # Re-dispatch AFTER the commit so the new task picks up the freshly
        # `queued` row when it runs `get_job`.
        for job in orphans:
            generate_subtitles.delay(job.id)
        return len(orphans)


@worker_ready.connect  # pragma: no cover (signal-driven; behaviour covered by unit tests of `_recover_orphans`)
def _on_worker_ready(sender, **kwargs):  # type: ignore[no-untyped-def]
    """Run the orphan-recovery sweep when this worker comes online.

    Celery's signal dispatcher already wraps each handler in its own
    try/except and logs any raised exception without aborting the worker, so
    we deliberately do NOT add a local try/except here — letting the failure
    surface in the worker log (with the original traceback) is more useful
    than swallowing it under a broad catch.
    """
    count = asyncio.run(_recover_orphans())
    if count:
        logger.info("orphan-recovery: re-queued %d job(s) at worker startup", count)
    else:
        logger.info("orphan-recovery: no orphan jobs found at worker startup")
