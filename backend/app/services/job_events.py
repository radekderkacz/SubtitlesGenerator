"""SSE event publication helpers.

The Redis channel name and event payload shape are the contract between
the API process and the worker process. Both publish to this channel:
- ``app.worker.tasks._publish_event`` (worker, mid-pipeline)
- ``publish_job_update`` here (API, on cancel / stop-all)

This module is import-safe from the API image — it carries no Celery /
ML / ffmpeg side effects. The worker imports the constants too so the
two paths can never drift.
"""
import asyncio
import json
from typing import Any

import redis.asyncio as aioredis

from app.core.config import app_settings
from app.models.orm import Job

REDIS_CHANNEL = "subtitles:job_updates"


def build_job_event_payload(job: Job) -> dict[str, Any]:
    return {
        "id": job.id,
        "status": job.status,
        "phase": job.phase,
        "progress": job.progress,
        "updated_at": job.updated_at.isoformat(),
        # Failure-surfacing fields so the SSE consumer can raise a clean
        # toast on processing→failed without doing a follow-up fetch
        # These are sent on every event so the
        # frontend has a stable shape; the cost is ~100 bytes per message.
        "file_path": job.file_path,
        "error_message": job.error_message,
        "verification_status": job.verification_status,
        "verification_score": job.verification_score,
        "verification_report": job.verification_report,
        "verified_at": job.verified_at.isoformat() if job.verified_at else None,
    }


async def publish_job_update(job: Job) -> None:
    redis_client = aioredis.from_url(app_settings.redis_url)
    try:
        await redis_client.publish(REDIS_CHANNEL, json.dumps(build_job_event_payload(job)))
    finally:
        await redis_client.aclose()


async def publish_job_updates(jobs: list[Job]) -> None:
    """Fan-out concurrent publishes (used by stop-all)."""
    if not jobs:
        return
    await asyncio.gather(*[publish_job_update(j) for j in jobs])
