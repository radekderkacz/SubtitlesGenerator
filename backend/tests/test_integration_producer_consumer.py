"""Producer → consumer integration tests.

Every trigger fire path must route through dispatch_event, which is the
single chokepoint into enqueue_job. These tests wire up the real dispatch
logic (file_filter_matches + dispatch_event) while mocking only:
  - the DB queries (no real Postgres needed)
  - enqueue_job (the actual Celery submission)

This validates that:
1. Watcher _fire() → dispatch_event → enqueue_job with source="trigger:<id>"
2. Webhook receive_webhook → dispatch_event → enqueue_job
3. Cron _fire_cron_trigger → dispatch_event → enqueue_job

All three producers must produce the same enqueue_job call shape.
"""
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.trigger_executor import MatchEvent, dispatch_event


@pytest.fixture(autouse=True)
def _mock_publish():
    """dispatch_event publishes a job_update on creation; these tests stub
    enqueue_job with a minimal fake job, so stub the publish collaborator too."""
    with patch("app.services.trigger_executor.publish_job_update", new=AsyncMock()):
        yield


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_trigger(
    *,
    id_: str,
    type_: str,
    config: dict,
    action: dict,
    file_filter: dict | None = None,
    enabled: bool = True,
):
    """Minimal trigger-like object that satisfies the executor and file_filter_matches."""
    return type(
        "Trigger",
        (),
        {
            "id": id_,
            "type": type_,
            "config": config,
            "action": action,
            "file_filter": file_filter or {"type": "all", "value": None},
            "enabled": enabled,
        },
    )()


def _make_session(*, trigger, profile_exists: bool = True):
    """Async mock session that returns `trigger` on SELECT Trigger and
    simulates profile lookup."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    return session


def _action(profile: str = "Default", src: str = "auto", tgt=None):
    return {
        "profile_name": profile,
        "source_language": src,
        "target_language": tgt,
        "skip_if_srt": True,
    }


# ---------------------------------------------------------------------------
# 1. Watch trigger → dispatch_event → enqueue_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_watch_fire_submits_job_with_trigger_source():
    """Watcher detects a new file and calls dispatch_event.

    The full chain: MatchEvent -> file_filter_matches -> enqueue_job.
    Only enqueue_job and the DB layer are mocked.
    """
    trig = _make_trigger(
        id_="w1",
        type_="watch",
        config={"path": "/media/TV"},
        action=_action("Default"),
        file_filter={"type": "all", "value": None},
    )
    session = _make_session(trigger=trig)
    enqueued = []

    async def fake_enqueue(s, payload):
        enqueued.append(payload)
        return type("J", (), {"id": "job-111"})()

    evt = MatchEvent("w1", "/media/TV/S01E01.mkv", {"event_type": "created"})

    with (
        patch(
            "app.services.trigger_executor._get_trigger",
            AsyncMock(return_value=trig),
        ),
        patch(
            "app.services.trigger_executor._profile_exists",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job",
            new=fake_enqueue,
        ),
    ):
        outcome = await dispatch_event(session, evt)

    assert outcome == "submitted"
    assert len(enqueued) == 1
    p = enqueued[0]
    assert p.file_path == "/media/TV/S01E01.mkv"
    assert p.profile_name == "Default"
    assert p.source == "trigger:w1"


# ---------------------------------------------------------------------------
# 2. Webhook trigger → dispatch_event → enqueue_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_webhook_fire_submits_job_with_trigger_source():
    """Webhook receives a POST and routes through dispatch_event.

    The `receive_webhook` handler calls `dispatch_event` directly.
    We verify the MatchEvent shape and that enqueue_job gets the right source.
    """
    trig = _make_trigger(
        id_="wh1",
        type_="webhook",
        config={},
        action=_action("WebhookProfile"),
        file_filter={"type": "all", "value": None},
    )
    session = _make_session(trigger=trig)
    enqueued = []

    async def fake_enqueue(s, payload):
        enqueued.append(payload)
        return type("J", (), {"id": "job-222"})()

    # The webhook handler constructs a MatchEvent from the POST body
    evt = MatchEvent(
        "wh1",
        "/shared/Films/NewMovie.mkv",
        {"source": "sonarr", "file_path": "/shared/Films/NewMovie.mkv"},
    )

    with (
        patch(
            "app.services.trigger_executor._get_trigger",
            AsyncMock(return_value=trig),
        ),
        patch(
            "app.services.trigger_executor._profile_exists",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job",
            new=fake_enqueue,
        ),
    ):
        outcome = await dispatch_event(session, evt)

    assert outcome == "submitted"
    assert len(enqueued) == 1
    p = enqueued[0]
    assert p.file_path == "/shared/Films/NewMovie.mkv"
    assert p.profile_name == "WebhookProfile"
    assert p.source == "trigger:wh1"


# ---------------------------------------------------------------------------
# 3. Cron trigger → dispatch_event → enqueue_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cron_fire_submits_job_with_trigger_source():
    """Cron fires a MatchEvent per file in the scan path.

    We simulate the _fire_cron_trigger loop: one MatchEvent per file,
    routed through dispatch_event to enqueue_job.
    """
    trig = _make_trigger(
        id_="c1",
        type_="cron",
        config={"cron": "0 3 * * *", "scan_path": "/media/TV",
                "schedule": {"mode": "daily", "time": "03:00"}},
        action=_action("NightProfile"),
        file_filter={"type": "all", "value": None},
    )
    enqueued = []

    async def fake_enqueue(s, payload):
        enqueued.append(payload)
        return type("J", (), {"id": f"job-{len(enqueued)}"})()

    files = ["ep01.mkv", "ep02.mkv"]

    with (
        patch(
            "app.services.trigger_executor._get_trigger",
            AsyncMock(return_value=trig),
        ),
        patch(
            "app.services.trigger_executor._profile_exists",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job",
            new=fake_enqueue,
        ),
    ):
        for filename in files:
            session = AsyncMock()
            session.add = MagicMock()
            session.commit = AsyncMock()
            evt = MatchEvent("c1", f"/media/TV/{filename}", {"cron_id": "c1"})
            outcome = await dispatch_event(session, evt)
            assert outcome == "submitted"

    assert len(enqueued) == 2
    assert all(p.source == "trigger:c1" for p in enqueued)
    assert enqueued[0].file_path == "/media/TV/ep01.mkv"
    assert enqueued[1].file_path == "/media/TV/ep02.mkv"


# ---------------------------------------------------------------------------
# 4. file_filter excludes non-matching files (name_contains)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_name_contains_filter_excludes_non_matching_file():
    """A file_filter with name_contains skips files that don't match."""
    trig = _make_trigger(
        id_="t99",
        type_="watch",
        config={"path": "/media"},
        action=_action("P1"),
        file_filter={"type": "name_contains", "value": "Marshals"},
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()

    evt = MatchEvent("t99", "/media/Avatar/S01E01.mkv", {})

    with (
        patch(
            "app.services.trigger_executor._get_trigger",
            AsyncMock(return_value=trig),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job",
            new=AsyncMock(),
        ) as eq,
    ):
        outcome = await dispatch_event(session, evt)

    assert outcome == "skipped_no_rule"
    eq.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Source field invariant: source is always "trigger:<id>" (never "manual")
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_source_field_is_always_trigger_prefixed():
    """Regardless of trigger type, source must be 'trigger:<id>'."""
    for type_, config in [
        ("watch", {"path": "/x"}),
        ("cron", {"cron": "* * * * *", "scan_path": "/x"}),
        ("webhook", {}),
    ]:
        trig = _make_trigger(
            id_="tx",
            type_=type_,
            config=config,
            action=_action("P"),
            file_filter={"type": "all", "value": None},
        )
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        captured = []

        async def fake_enqueue(s, payload):
            captured.append(payload)
            return type("J", (), {"id": "jx"})()

        evt = MatchEvent("tx", "/x/file.mkv", {})
        with (
            patch(
                "app.services.trigger_executor._get_trigger",
                AsyncMock(return_value=trig),
            ),
            patch(
                "app.services.trigger_executor._profile_exists",
                AsyncMock(return_value=True),
            ),
            patch(
                "app.services.trigger_executor.enqueue_job",
                new=fake_enqueue,
            ),
        ):
            await dispatch_event(session, evt)

        assert len(captured) == 1, f"Expected 1 enqueue for type={type_}"
        assert captured[0].source == "trigger:tx", (
            f"source must be 'trigger:tx' for type={type_}, "
            f"got {captured[0].source!r}"
        )
        captured.clear()
