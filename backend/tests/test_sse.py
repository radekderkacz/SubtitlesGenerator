import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.sse import _event_stream, _REDIS_CHANNEL


def _make_pubsub_mock(get_message_side_effect=None):
    pubsub = MagicMock()
    pubsub.subscribe = AsyncMock()
    pubsub.unsubscribe = AsyncMock()
    pubsub.aclose = AsyncMock()
    if get_message_side_effect is None:
        pubsub.get_message = AsyncMock(return_value=None)
    else:
        pubsub.get_message = AsyncMock(side_effect=get_message_side_effect)
    return pubsub


def _make_redis_mock(pubsub):
    redis = MagicMock()
    redis.pubsub = MagicMock(return_value=pubsub)
    redis.aclose = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# AC2: initial queue_state event with current jobs and replayed_at
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_initial_queue_state():
    queue_state_json = json.dumps({
        "jobs": [{
            "id": "job-1",
            "status": "queued",
            "phase": None,
            "progress": 0,
            "file_path": "/media/Film.mkv",
            "target_language": "en",
        }],
        "replayed_at": "2026-04-28T12:00:00+00:00",
    })
    pubsub = _make_pubsub_mock()
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value=queue_state_json)):
        gen = _event_stream()
        event = await gen.__anext__()
        await gen.aclose()

    assert event["event"] == "queue_state"
    payload = json.loads(event["data"])
    assert "jobs" in payload
    assert "replayed_at" in payload
    assert payload["jobs"][0]["id"] == "job-1"
    assert payload["jobs"][0]["status"] == "queued"


# ---------------------------------------------------------------------------
# AC3, AC4: forward Redis pub/sub messages as job_update SSE events
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_forwards_redis_messages():
    """First idle poll → heartbeat; next pubsub message → job_update event."""
    job_update_payload = (
        '{"id":"j1","status":"processing","phase":"transcribing",'
        '"progress":40,"updated_at":"2026-04-28T12:00:00+00:00"}'
    )

    yielded = [
        None,  # first poll empty → heartbeat
        {"type": "message", "data": job_update_payload.encode("utf-8")},
    ]
    call_index = {"i": 0}

    async def fake_get_message(**_kwargs):
        i = call_index["i"]
        call_index["i"] = i + 1
        return yielded[i] if i < len(yielded) else None

    pubsub = _make_pubsub_mock(get_message_side_effect=fake_get_message)
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value='{"jobs":[],"replayed_at":"now"}')):
        gen = _event_stream()
        first = await gen.__anext__()
        assert first["event"] == "queue_state"

        # Idle poll → heartbeat
        second = await gen.__anext__()
        assert second["event"] == "heartbeat"
        assert second["data"] == "{}"

        # Real pubsub message → job_update
        third = await gen.__anext__()
        await gen.aclose()

    assert third["event"] == "job_update"
    assert third["data"] == job_update_payload
    pubsub.subscribe.assert_awaited_with(_REDIS_CHANNEL)


@pytest.mark.asyncio
async def test_sse_emits_heartbeat_on_idle():
    """Sustained idle pubsub → repeated heartbeat events."""
    pubsub = _make_pubsub_mock(get_message_side_effect=AsyncMock(return_value=None))
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value='{"jobs":[],"replayed_at":"now"}')):
        gen = _event_stream()
        await gen.__anext__()  # consume queue_state
        first_heartbeat = await gen.__anext__()
        second_heartbeat = await gen.__anext__()
        await gen.aclose()

    assert first_heartbeat == {"event": "heartbeat", "data": "{}"}
    assert second_heartbeat == {"event": "heartbeat", "data": "{}"}


# ---------------------------------------------------------------------------
# AC4: bytes payload from Redis is decoded to string before yield
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_decodes_bytes_payload():
    yielded = [{"type": "message", "data": b'{"id":"x"}'}]
    call_index = {"i": 0}

    async def fake_get_message(**_kwargs):
        i = call_index["i"]
        call_index["i"] = i + 1
        return yielded[i] if i < len(yielded) else None

    pubsub = _make_pubsub_mock(get_message_side_effect=fake_get_message)
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value="{}")):
        gen = _event_stream()
        await gen.__anext__()  # discard queue_state
        event = await gen.__anext__()
        await gen.aclose()

    assert isinstance(event["data"], str)
    assert event["data"] == '{"id":"x"}'


# ---------------------------------------------------------------------------
# AC5: cleanup on disconnect — unsubscribe + close + aclose called via finally
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_cleanup_on_disconnect():
    pubsub = _make_pubsub_mock()
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value="{}")):
        gen = _event_stream()
        await gen.__anext__()  # consume queue_state, generator now blocked in pubsub loop
        await gen.aclose()      # closing the generator runs the finally block

    pubsub.unsubscribe.assert_awaited_with(_REDIS_CHANNEL)
    pubsub.aclose.assert_awaited()
    redis.aclose.assert_awaited()


# ---------------------------------------------------------------------------
# AC3: subscribe is called with the canonical channel name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_subscribes_to_canonical_channel():
    pubsub = _make_pubsub_mock()
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value="{}")):
        gen = _event_stream()
        await gen.__anext__()
        # one tick of the loop so subscribe is invoked
        await gen.aclose()

    assert _REDIS_CHANNEL == "subtitles:job_updates"
    pubsub.subscribe.assert_awaited_with("subtitles:job_updates")


# ---------------------------------------------------------------------------
# Defensive: subscribe failure must not leak the connection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sse_cleanup_when_subscribe_fails():
    """If pubsub.subscribe raises (Redis down), the redis_client and pubsub must still be closed."""
    pubsub = _make_pubsub_mock()
    pubsub.subscribe = AsyncMock(side_effect=ConnectionError("redis unreachable"))
    redis = _make_redis_mock(pubsub)

    with patch("app.api.sse.aioredis.from_url", return_value=redis), \
         patch("app.api.sse._build_queue_state", AsyncMock(return_value="{}")):
        gen = _event_stream()
        with pytest.raises(ConnectionError, match="redis unreachable"):
            await gen.__anext__()

    pubsub.aclose.assert_awaited()
    redis.aclose.assert_awaited()


# ---------------------------------------------------------------------------
# Regression: GET /api/v1/jobs/stream must resolve to SSE, not /jobs/{job_id}
# ---------------------------------------------------------------------------

def test_sse_route_resolves_before_jobs_path_param():
    """Route registration order: /jobs/stream must resolve to the SSE endpoint, not
    to /jobs/{job_id} treating 'stream' as a job id. Inspect the FastAPI route table
    directly — exercising via streaming HTTP hangs the test client because the
    pub/sub loop never naturally terminates under ASGITransport."""
    from app.main import app
    from app.api.sse import jobs_stream

    routes_for_stream = [
        r for r in app.routes
        if getattr(r, "path", "") == "/api/v1/jobs/stream"
    ]
    assert len(routes_for_stream) == 1, "expected exactly one route at /api/v1/jobs/stream"
    # The route's endpoint function must be the SSE jobs_stream, not jobs.get_job
    assert routes_for_stream[0].endpoint is jobs_stream
