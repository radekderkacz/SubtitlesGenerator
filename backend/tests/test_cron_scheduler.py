"""Tests for cron_scheduler — periodic Beat task body."""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.cron_scheduler import _evaluate_async, MAX_FILES_PER_FIRE


def _mock_session_ctx():
    """Return an async context manager that yields a mock session."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def _ctx():
        yield mock_session

    return _ctx


@pytest.mark.asyncio
async def test_due_trigger_walks_scan_path_and_dispatches():
    trig = MagicMock(
        id="c1",
        type="cron",
        config={"cron": "*/1 * * * *", "scan_path": "/scan"},
        action={"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "all", "value": None},
    )
    with (
        patch(
            "app.services.cron_scheduler._load_cron_triggers",
            AsyncMock(return_value=[trig]),
        ),
        patch(
            "app.services.cron_scheduler._last_fire_at",
            AsyncMock(return_value=None),
        ),
        patch("os.walk", return_value=[("/scan", [], ["a.mkv", "b.mkv"])]),
        patch(
            "app.services.cron_scheduler.dispatch_event", new=AsyncMock()
        ) as disp,
        patch(
            "app.services.cron_scheduler._SessionLocal",
            _mock_session_ctx(),
        ),
    ):
        await _evaluate_async(datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc))
    assert disp.await_count == 2


@pytest.mark.asyncio
async def test_scan_limit_emits_skipped_for_overflow():
    trig = MagicMock(
        id="c1",
        type="cron",
        config={"cron": "* * * * *", "scan_path": "/scan"},
        action={"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "all", "value": None},
    )
    over = [f"f{i}.mkv" for i in range(MAX_FILES_PER_FIRE + 5)]
    with (
        patch(
            "app.services.cron_scheduler._load_cron_triggers",
            AsyncMock(return_value=[trig]),
        ),
        patch(
            "app.services.cron_scheduler._last_fire_at",
            AsyncMock(return_value=None),
        ),
        patch("os.walk", return_value=[("/scan", [], over)]),
        patch(
            "app.services.cron_scheduler.dispatch_event", new=AsyncMock()
        ) as disp,
        patch(
            "app.services.cron_scheduler._record_skipped_scan_limit",
            new=AsyncMock(),
        ) as skip,
        patch(
            "app.services.cron_scheduler._SessionLocal",
            _mock_session_ctx(),
        ),
    ):
        await _evaluate_async(datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc))
    assert disp.await_count == MAX_FILES_PER_FIRE
    assert skip.await_count == 5


# ---------------------------------------------------------------------------
# WS5 (2026-07 audit): malformed-trigger isolation, empty-scan stamp,
# fresh-file (still-copying) skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_malformed_trigger_does_not_halt_others():
    """A cron trigger whose config lost its 'cron' key (KeyError) must not
    abort evaluation of the remaining triggers."""
    bad = MagicMock(id="bad", type="cron", config={}, last_fired_at=None)
    good = MagicMock(
        id="good", type="cron",
        config={"cron": "*/1 * * * *", "scan_path": "/scan"},
        action={"profile_name": "P1"}, file_filter={"type": "all", "value": None},
        last_fired_at=None,
    )
    with (
        patch("app.services.cron_scheduler._load_cron_triggers",
              AsyncMock(return_value=[bad, good])),
        patch("app.services.cron_scheduler._last_fire_at", AsyncMock(return_value=None)),
        patch("os.walk", return_value=[("/scan", [], ["a.mkv"])]),
        patch("app.services.cron_scheduler.dispatch_event", new=AsyncMock()) as disp,
        patch("app.services.cron_scheduler._SessionLocal", _mock_session_ctx()),
    ):
        await _evaluate_async(datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc))
    assert disp.await_count == 1  # the good trigger still fired


@pytest.mark.asyncio
async def test_empty_scan_stamps_last_fired_at():
    """A fire that dispatches nothing must still record the fire, otherwise
    the trigger re-fires (and re-walks the NAS) every minute forever."""
    trig = MagicMock(
        id="c1", type="cron",
        config={"cron": "*/1 * * * *", "scan_path": "/scan"},
        action={"profile_name": "P1"}, file_filter={"type": "all", "value": None},
        last_fired_at=None,
    )
    row = MagicMock()
    ctx = _mock_session_ctx()
    session = None
    # extract the session the ctx yields
    import asyncio as _aio
    async def _grab():
        nonlocal session
        async with ctx() as s:
            session = s
    _aio.get_event_loop
    with (
        patch("app.services.cron_scheduler._load_cron_triggers", AsyncMock(return_value=[trig])),
        patch("app.services.cron_scheduler._last_fire_at", AsyncMock(return_value=None)),
        patch("os.walk", return_value=[("/scan", [], [])]),
        patch("app.services.cron_scheduler.dispatch_event", new=AsyncMock()) as disp,
        patch("app.services.cron_scheduler._SessionLocal", ctx),
    ):
        await _grab()
        session.get = AsyncMock(return_value=row)
        await _evaluate_async(datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc))
    assert disp.await_count == 0
    assert isinstance(row.last_fired_at, datetime)


@pytest.mark.asyncio
async def test_fresh_files_are_skipped_as_still_copying():
    trig = MagicMock(
        id="c1", type="cron",
        config={"cron": "*/1 * * * *", "scan_path": "/scan"},
        action={"profile_name": "P1"}, file_filter={"type": "all", "value": None},
        last_fired_at=None,
    )
    now = datetime(2026, 5, 20, 0, 0, 30, tzinfo=timezone.utc)
    with (
        patch("app.services.cron_scheduler._load_cron_triggers", AsyncMock(return_value=[trig])),
        patch("app.services.cron_scheduler._last_fire_at", AsyncMock(return_value=None)),
        patch("os.walk", return_value=[("/scan", [], ["fresh.mkv"])]),
        patch("os.path.getmtime", return_value=now.timestamp() - 10),
        patch("app.services.cron_scheduler.dispatch_event", new=AsyncMock()) as disp,
        patch("app.services.cron_scheduler._SessionLocal", _mock_session_ctx()),
    ):
        await _evaluate_async(now)
    assert disp.await_count == 0
