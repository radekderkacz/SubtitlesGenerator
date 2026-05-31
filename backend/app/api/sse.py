import json
from datetime import datetime, timezone
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.core.config import app_settings
from app.core.database import AsyncSessionLocal
from app.models.schemas import JobResponse
from app.services import job_service

router = APIRouter()

# Must stay in sync with app.worker.tasks._REDIS_CHANNEL.
# Duplicated here intentionally — `tasks.py` carries worker-only side effects
# and must not be imported into the API image.
_REDIS_CHANNEL = "subtitles:job_updates"
# `pubsub.get_message(timeout=2.0)` doubles as the heartbeat cadence: when no
# real job_update arrives within the window, we emit a `heartbeat` event so
# the frontend's connection indicator can age "time since last event" without
# depending on actual job activity. 2s leaves comfortable margin under the
# 5s "amber" threshold.
_HEARTBEAT_INTERVAL_S = 2.0


async def _build_queue_state() -> str:
    async with AsyncSessionLocal() as session:
        jobs = await job_service.list_jobs(session)
        job_dicts = [
            JobResponse.model_validate(j, from_attributes=True).model_dump(mode="json")
            for j in jobs
        ]
    payload = {
        "jobs": job_dicts,
        "replayed_at": datetime.now(timezone.utc).isoformat(),
    }
    return json.dumps(payload)


async def _event_stream() -> AsyncGenerator[dict, None]:
    """Yield SSE events. EventSourceResponse cancels this generator on client disconnect;
    the 1s pubsub timeout gives a natural preemption point so cancellation lands within ~1s.

    Subscribe BEFORE building queue_state so events published during the snapshot query
    are buffered by Redis and delivered to the client — no events are missed.
    """
    redis_client = aioredis.from_url(app_settings.redis_url)
    pubsub = redis_client.pubsub()
    try:
        await pubsub.subscribe(_REDIS_CHANNEL)
    except Exception:
        await pubsub.aclose()
        await redis_client.aclose()
        raise

    try:
        yield {"event": "queue_state", "data": await _build_queue_state()}
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=_HEARTBEAT_INTERVAL_S,
            )
            if message is None:
                # No real event in the window — emit a heartbeat so the
                # frontend's "time since last event" indicator stays current.
                yield {"event": "heartbeat", "data": "{}"}
                continue
            if message.get("type") != "message":
                continue
            data = message["data"]
            if isinstance(data, bytes):
                data = data.decode("utf-8")
            yield {"event": "job_update", "data": data}
    finally:
        try:
            await pubsub.unsubscribe(_REDIS_CHANNEL)
        finally:
            await pubsub.aclose()
            await redis_client.aclose()


@router.get(
    "/jobs/stream",
    responses={200: {"description": "Server-Sent Events stream of job updates"}},
)
async def jobs_stream():
    return EventSourceResponse(_event_stream())
