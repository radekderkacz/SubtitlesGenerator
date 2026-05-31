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
