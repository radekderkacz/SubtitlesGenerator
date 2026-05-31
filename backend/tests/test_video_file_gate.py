"""The Automations cron-scan + manual-fire loops must dispatch ONLY video
files. Regression test: before the fix, `os.walk` in both loops dispatched
every file, submitting `.srt`/`.jpg`/`.nfo` sidecars as transcription jobs
(surfaced by the first real end-to-end test of the redesigned triggers).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.media import is_video_file


def test_is_video_file_accepts_video_extensions():
    for ext in (".mkv", ".mp4", ".avi", ".m4v", ".mov"):
        assert is_video_file(f"/x/movie{ext}")
    assert is_video_file("/x/Movie.MKV")  # case-insensitive


def test_is_video_file_rejects_sidecars():
    for p in (
        "/x/movie.srt",
        "/x/movie.en.srt",
        "/x/movie-thumb.jpg",
        "/x/movie.nfo",
        "/x/movie",
        "/x/movie.txt",
    ):
        assert not is_video_file(p)


@pytest.mark.asyncio
async def test_cron_fire_dispatches_only_video_files():
    from app.services import cron_scheduler

    trig = MagicMock(id="c1", config={"scan_path": "/scan"})
    walk = [("/scan", [], ["ep.mkv", "ep.srt", "ep-thumb.jpg", "ep.nfo", "ep2.mp4"])]
    dispatched: list[str] = []

    async def fake_dispatch(_session, evt):
        dispatched.append(evt.file_path)

    sl = MagicMock()
    sl.return_value.__aenter__ = AsyncMock(return_value=AsyncMock())
    sl.return_value.__aexit__ = AsyncMock(return_value=None)
    with patch("app.services.cron_scheduler.os.walk", return_value=walk), patch(
        "app.services.cron_scheduler.dispatch_event", new=fake_dispatch
    ), patch("app.services.cron_scheduler._SessionLocal", new=sl):
        await cron_scheduler._fire_cron_trigger(trig, datetime.now(timezone.utc))

    assert dispatched == ["/scan/ep.mkv", "/scan/ep2.mp4"]


@pytest.mark.asyncio
async def test_manual_fire_endpoint_dispatches_only_video_files(client):
    trig = MagicMock(type="watch", config={"path": "/scan"})
    walk = [("/scan", [], ["ep.mkv", "ep.srt", "ep-thumb.jpg", "ep.nfo", "ep2.mp4"])]
    dispatched: list[str] = []

    async def fake_dispatch(_session, evt):
        dispatched.append(evt.file_path)

    with patch(
        "app.api.triggers.trigger_service.get_trigger",
        new=AsyncMock(return_value=trig),
    ), patch("app.api.triggers.os.walk", return_value=walk), patch(
        "app.api.triggers.dispatch_event", new=fake_dispatch
    ):
        resp = await client.post("/api/v1/triggers/t1/fire")

    assert resp.status_code == 200
    assert resp.json()["fired"] == 2
    assert dispatched == ["/scan/ep.mkv", "/scan/ep2.mp4"]
