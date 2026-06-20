"""Coverage backfill for app.services.job_events."""
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.orm import Job
from app.services.job_events import (
    REDIS_CHANNEL,
    build_job_event_payload,
    publish_job_update,
    publish_job_updates,
)


def _make_job(**overrides) -> Job:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        status="processing",
        phase="transcribing",
        progress=42,
        file_path="/media/Foo.mkv",
        source_language=None,
        target_language="en",
        model_size="large-v3",
        translation_provider=None,
        translation_model=None,
        log_path=None,
        error_message=None,
        source="manual",
        created_at=now,
        updated_at=now,
        completed_at=None,
        jellyfin_refreshed_at=None,
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_redis_channel_constant():
    assert REDIS_CHANNEL == "subtitles:job_updates"


def test_build_payload_includes_all_required_fields():
    job = _make_job()
    payload = build_job_event_payload(job)
    assert set(payload) == {
        "id",
        "status",
        "phase",
        "progress",
        "updated_at",
        # surfaced so the SSE consumer can toast on
        # failure without a follow-up GET /jobs/{id} round-trip.
        "file_path",
        "error_message",
        # subtitle verification — surfaced so the live badge updates over SSE.
        "verification_status",
        "verification_score",
        "verification_report",
        "verified_at",
    }
    assert payload["status"] == "processing"
    assert payload["phase"] == "transcribing"
    assert payload["progress"] == 42
    # ISO-8601 string, parseable
    assert datetime.fromisoformat(payload["updated_at"])


def test_build_payload_surfaces_failure_fields():
    """For frontend toast on processing→failed transition."""
    job = _make_job(
        status="failed",
        file_path="/mnt/nas/film.mkv",
        error_message="CUDA out of memory",
    )
    payload = build_job_event_payload(job)
    assert payload["file_path"] == "/mnt/nas/film.mkv"
    assert payload["error_message"] == "CUDA out of memory"


def test_build_payload_handles_null_phase():
    job = _make_job(phase=None, status="queued")
    payload = build_job_event_payload(job)
    assert payload["phase"] is None
    assert payload["status"] == "queued"


@pytest.mark.asyncio
async def test_publish_job_update_calls_redis_with_payload():
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock()
    fake_redis.aclose = AsyncMock()

    with patch(
        "app.services.job_events.aioredis.from_url", return_value=fake_redis,
    ):
        await publish_job_update(_make_job(id="abc"))

    fake_redis.publish.assert_awaited_once()
    channel, body = fake_redis.publish.call_args.args
    assert channel == REDIS_CHANNEL
    parsed = json.loads(body)
    assert parsed["id"] == "abc"
    fake_redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_job_update_closes_client_even_when_publish_fails():
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(side_effect=RuntimeError("network down"))
    fake_redis.aclose = AsyncMock()

    with patch(
        "app.services.job_events.aioredis.from_url", return_value=fake_redis,
    ), pytest.raises(RuntimeError, match="network down"):
        await publish_job_update(_make_job())

    fake_redis.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_job_updates_returns_early_for_empty_list():
    """No jobs → no Redis client created, no error."""
    with patch("app.services.job_events.aioredis.from_url") as from_url:
        await publish_job_updates([])
    from_url.assert_not_called()


@pytest.mark.asyncio
async def test_publish_job_updates_fans_out_per_job():
    """N jobs → N publish calls (concurrent via asyncio.gather)."""
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock()
    fake_redis.aclose = AsyncMock()

    with patch(
        "app.services.job_events.aioredis.from_url", return_value=fake_redis,
    ):
        await publish_job_updates([_make_job() for _ in range(3)])

    assert fake_redis.publish.await_count == 3
