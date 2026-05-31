"""Tests for dispatch_event — the single chokepoint into enqueue_job."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.trigger_executor import MatchEvent, dispatch_event


def _trig(action=None, file_filter=None, type_="watch", config=None):
    return type(
        "T",
        (),
        {
            "id": "t1",
            "type": type_,
            "config": config or {"path": "/x"},
            "action": action,
            "file_filter": file_filter,
        },
    )()


@pytest.mark.asyncio
async def test_dispatch_no_match_writes_skipped_no_rule():
    # Use a video extension so the new video-gate doesn't pre-empt the
    # file_filter check we want to exercise here.
    evt = MatchEvent("t1", "/x/episode.mp4", {})
    # name_contains "S01E02" won't match "episode.mp4"
    trig = _trig(
        action={"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "name_contains", "value": "S01E02"},
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    with (
        patch(
            "app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)
        ),
        patch(
            "app.services.trigger_executor.enqueue_job", new=AsyncMock()
        ) as eq,
    ):
        outcome = await dispatch_event(session, evt)
    assert outcome == "skipped_no_rule"
    eq.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_match_unknown_profile_failed_dispatch():
    evt = MatchEvent("t1", "/x/m.mkv", {})
    trig = _trig(
        action={
            "profile_name": "GHOST",
            "source_language": None,
            "target_language": None,
            "skip_if_srt": True,
        },
        file_filter={"type": "all", "value": None},
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    with (
        patch(
            "app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)
        ),
        patch(
            "app.services.trigger_executor._profile_exists",
            AsyncMock(return_value=False),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job", new=AsyncMock()
        ) as eq,
    ):
        outcome = await dispatch_event(session, evt)
    assert outcome == "failed_dispatch"
    eq.assert_not_called()


# Video-file gate at the chokepoint — every caller (watch/cron/webhook/manual)
# must converge on the same skip-non-video contract enforced in dispatch_event.


def _accepting_trig():
    return _trig(
        action={
            "profile_name": "P1",
            "source_language": None,
            "target_language": None,
            "skip_if_srt": True,
        },
        file_filter={"type": "all", "value": None},
    )


async def _dispatch(evt: MatchEvent, trig=None):
    """Run dispatch_event with a trigger that would otherwise accept
    everything — so we're testing only the video gate, not file_filter
    or profile-existence side gates."""
    trig = trig or _accepting_trig()
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    enqueue_calls: list = []

    async def fake_enqueue(s, payload):
        enqueue_calls.append(payload)
        return type("J", (), {"id": "job-uuid"})()

    with (
        patch("app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)),
        patch("app.services.trigger_executor._profile_exists", AsyncMock(return_value=True)),
        patch("app.services.trigger_executor.enqueue_job", new=fake_enqueue),
    ):
        outcome = await dispatch_event(session, evt)
    return outcome, enqueue_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ext",
    [".mkv", ".mp4", ".avi", ".m4v", ".mov", ".MKV", ".Mp4", ".AVI"],
)
async def test_dispatch_accepts_every_known_video_extension(ext):
    """Every extension in VIDEO_EXTENSIONS must pass — case-insensitive."""
    evt = MatchEvent("t1", f"/x/Movie{ext}", {})
    outcome, enqueued = await _dispatch(evt)
    assert outcome == "submitted"
    assert len(enqueued) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/x/poster.jpg",                # the bug — Sonarr/Plex artwork
        "/x/fanart.jpg",
        "/x/landscape.jpg",
        "/x/logo.png",
        "/x/movie.nfo",                  # NFO metadata
        "/x/movie.srt",                  # subtitle sidecar
        "/x/movie.en.srt",
        "/x/notes.txt",
        "/x/no-extension",
        "/x/.hidden",
        "/x/Movie WEBDL-2160p.trickplay/320 - 10x10/0.jpg",  # nested Plex trickplay
        "/x/movie.mkv.partial",          # in-progress download — extension is .partial
    ],
)
async def test_dispatch_rejects_non_video_files(path):
    """Any non-video path — regardless of nesting, hidden status, or
    suspicious naming — must be dropped before enqueue."""
    evt = MatchEvent("t1", path, {})
    outcome, enqueued = await _dispatch(evt)
    assert outcome == "skipped_not_video"
    assert enqueued == []


@pytest.mark.asyncio
async def test_dispatch_video_gate_runs_before_file_filter():
    """A non-video file must be rejected even if file_filter=all would
    otherwise accept it. The gate is universal, not filter-conditional."""
    evt = MatchEvent("t1", "/x/poster.jpg", {})
    outcome, enqueued = await _dispatch(evt)
    assert outcome == "skipped_not_video"
    assert enqueued == []


@pytest.mark.asyncio
async def test_dispatch_video_gate_runs_before_profile_check():
    """Order matters: if the file isn't a video we never get to
    profile-existence (it'd return failed_dispatch and confuse users)."""
    evt = MatchEvent("t1", "/x/poster.jpg", {})
    # Profile EXPLICITLY doesn't exist; should still get skipped_not_video,
    # not failed_dispatch.
    trig = _trig(
        action={"profile_name": "GHOST", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "all", "value": None},
    )
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    with (
        patch("app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)),
        patch("app.services.trigger_executor._profile_exists", AsyncMock(return_value=False)),
        patch("app.services.trigger_executor.enqueue_job", new=AsyncMock()),
    ):
        outcome = await dispatch_event(session, evt)
    assert outcome == "skipped_not_video"


@pytest.mark.asyncio
async def test_dispatch_records_event_for_non_video_so_user_sees_activity():
    """The user should see a row in Recent Activity even for skipped files,
    so they understand why their JPG didn't kick off a job."""
    evt = MatchEvent("t1", "/x/poster.jpg", {})
    trig = _accepting_trig()
    session = AsyncMock()
    added = []
    session.add = MagicMock(side_effect=added.append)
    session.commit = AsyncMock()
    with (
        patch("app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)),
        patch("app.services.trigger_executor._profile_exists", AsyncMock(return_value=True)),
        patch("app.services.trigger_executor.enqueue_job", new=AsyncMock()) as eq,
    ):
        await dispatch_event(session, evt)
    # exactly one TriggerEvent row written
    assert len(added) == 1
    assert added[0].outcome == "skipped_not_video"
    assert added[0].job_id is None
    eq.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_match_submits_with_trigger_source():
    evt = MatchEvent("t1", "/x/m.mkv", {"original_event_type": "created"})
    action = {
        "profile_name": "P1",
        "source_language": "en",
        "target_language": "pl",
        "skip_if_srt": True,
    }
    trig = _trig(action=action, file_filter={"type": "all", "value": None})
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    enqueued = []

    async def fake_enqueue(s, payload):
        enqueued.append(payload)
        return type("J", (), {"id": "job-uuid"})()

    with (
        patch(
            "app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)
        ),
        patch(
            "app.services.trigger_executor._profile_exists",
            AsyncMock(return_value=True),
        ),
        patch(
            "app.services.trigger_executor.enqueue_job", new=fake_enqueue
        ),
    ):
        outcome = await dispatch_event(session, evt)
    assert outcome == "submitted"
    assert enqueued[0].file_path == "/x/m.mkv"
    assert enqueued[0].source == "trigger:t1"
