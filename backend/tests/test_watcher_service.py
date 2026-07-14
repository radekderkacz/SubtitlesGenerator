"""Watchdog file watcher service.

Unit tests focus on the pure decision functions (extension filter +
sibling-SRT skip) and on the WatcherService lifecycle (start / stop /
restart). The observer thread is exercised through a small integration
test that drops a real file into a tmp_path and asserts the callback
fires.
"""
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.watcher import (
    VIDEO_EXTENSIONS,
    Watcher,
    WatcherService,
    has_sibling_srt,
    should_enqueue,
    _schedule_observer,
)


# ---------------------------------------------------------------------------
# Pure-function eligibility checks
# ---------------------------------------------------------------------------

def test_video_extensions_set_matches_ac():
    assert VIDEO_EXTENSIONS == frozenset({".mkv", ".mp4", ".avi", ".m4v", ".mov"})


def test_should_enqueue_rejects_non_video_extensions(tmp_path):
    txt = tmp_path / "notes.txt"
    txt.write_text("hi")
    assert should_enqueue(str(txt)) is False


def test_should_enqueue_rejects_when_sibling_srt_exists(tmp_path):
    video = tmp_path / "Foo.mkv"
    video.write_bytes(b"x")
    (tmp_path / "Foo.en.srt").write_text("1\n00:00:00 --> 00:00:01\nhi\n")
    assert should_enqueue(str(video)) is False


def test_should_enqueue_accepts_video_without_srt(tmp_path):
    video = tmp_path / "Foo.mkv"
    video.write_bytes(b"x")
    assert should_enqueue(str(video)) is True


def test_should_enqueue_is_extension_case_insensitive(tmp_path):
    video = tmp_path / "Foo.MKV"
    video.write_bytes(b"x")
    assert should_enqueue(str(video)) is True


def test_has_sibling_srt_matches_bare_srt(tmp_path):
    """`<basename>.srt` (no language suffix) also counts as having SRT."""
    video = tmp_path / "Foo.mkv"
    video.write_bytes(b"x")
    (tmp_path / "Foo.srt").write_text("hi")
    assert has_sibling_srt(str(video)) is True


def test_has_sibling_srt_does_not_match_unrelated_files(tmp_path):
    video = tmp_path / "Foo.mkv"
    video.write_bytes(b"x")
    # Different stem
    (tmp_path / "Bar.en.srt").write_text("hi")
    assert has_sibling_srt(str(video)) is False


def test_has_sibling_srt_returns_false_when_folder_missing():
    assert has_sibling_srt("/does/not/exist/Foo.mkv") is False


# ---------------------------------------------------------------------------
# WatcherService lifecycle
# ---------------------------------------------------------------------------

def test_watcher_start_with_no_paths_is_noop():
    callback = MagicMock()
    service = WatcherService(callback)
    service.start([])
    assert service.paths == ()
    service.stop()  # safe even when never started


def test_watcher_start_skips_nonexistent_paths(tmp_path):
    """Non-existent paths are silently dropped; only real dirs are monitored."""
    callback = MagicMock()
    real_path = tmp_path / "real"
    real_path.mkdir()
    bogus_path = tmp_path / "ghost"

    service = WatcherService(callback)
    service.start([str(real_path), str(bogus_path)])
    try:
        # Only the real path makes it into service.paths.
        assert service.paths == (str(real_path),)
    finally:
        service.stop()


def test_watcher_restart_swaps_path_set(tmp_path):
    callback = MagicMock()
    a = tmp_path / "a"
    a.mkdir()
    b = tmp_path / "b"
    b.mkdir()

    service = WatcherService(callback)
    service.start([str(a)])
    assert service.paths == (str(a),)
    service.restart([str(b)])
    try:
        assert service.paths == (str(b),)
    finally:
        service.stop()


def test_watcher_stop_is_idempotent():
    service = WatcherService(MagicMock())
    service.stop()  # never started
    service.start([])
    service.stop()
    service.stop()  # second stop is fine


# ---------------------------------------------------------------------------
# Integration: real watchdog observer fires the callback
# ---------------------------------------------------------------------------

def test_watcher_invokes_callback_on_new_video(tmp_path):
    """Drop a .mkv into a watched folder, observer should call the callback
    via the FileSystemEventHandler within a couple of seconds."""
    detected: list[str] = []

    def on_detected(path: str) -> None:
        detected.append(path)

    service = WatcherService(on_detected)
    service.start([str(tmp_path)])
    try:
        target = tmp_path / "Sample.mkv"
        target.write_bytes(b"\x00" * 16)
        # Watchdog needs a tick to wake; poll up to 3s.
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not detected:
            time.sleep(0.1)
        assert detected == [str(target)]
    finally:
        service.stop()


def test_watcher_skips_video_when_srt_already_exists(tmp_path):
    detected: list[str] = []

    def on_detected(path: str) -> None:
        detected.append(path)

    # Pre-seed an SRT that matches the file we'll create
    (tmp_path / "Sample.en.srt").write_text("1\n00:00:00 --> 00:00:01\nhi\n")

    service = WatcherService(on_detected)
    service.start([str(tmp_path)])
    try:
        target = tmp_path / "Sample.mkv"
        target.write_bytes(b"\x00" * 16)
        time.sleep(1)  # give the observer a chance
        assert detected == []
    finally:
        service.stop()


# ---------------------------------------------------------------------------
# New Watcher (trigger-table-based, async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lifespan_starts_trigger_watcher(monkeypatch):
    """Regression guard. Automations V1 (PR #120) shipped without
    instantiating the trigger-table Watcher in the FastAPI lifespan,
    so watch triggers silently never fired on new files. Symptom:
    user creates a watch trigger on /shared/Movie, drops a file, nothing
    happens. Worker container had only Celery; no watcher process.
    """
    from unittest.mock import patch
    from app import main

    mock_watcher_instance = MagicMock()
    mock_watcher_instance.start = AsyncMock()
    mock_watcher_instance.stop = MagicMock()

    # Replace the Watcher class; legacy WatcherService is kept as-is and
    # also gets the no-op start that the current lifespan uses.
    monkeypatch.setattr("app.main.Watcher", lambda: mock_watcher_instance)

    # Stub the Settings-seed DB call so the test doesn't need Postgres.
    fake_session = MagicMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    fake_session.execute = AsyncMock()
    fake_session.commit = AsyncMock()
    monkeypatch.setattr("app.main.AsyncSessionLocal", lambda: fake_session)

    async with main.lifespan(main.app):
        mock_watcher_instance.start.assert_called_once()
        assert main.app.state.trigger_watcher is mock_watcher_instance

    # And it must be stopped on shutdown so the observer thread doesn't leak.
    mock_watcher_instance.stop.assert_called_once()


def _trap_run_coroutine_threadsafe(monkeypatch, scheduled: list[str]) -> None:
    """Replace asyncio.run_coroutine_threadsafe with a recorder. The
    coroutine is closed so pytest doesn't warn about "coroutine was never
    awaited"."""
    def _trap(coro, loop):
        scheduled.append("fired")
        coro.close()
    monkeypatch.setattr(
        "app.services.watcher.asyncio.run_coroutine_threadsafe", _trap
    )


@pytest.mark.parametrize("video_path", [
    "/x/movie.mkv", "/x/movie.mp4", "/x/Movie.MKV", "/x/m.mov",
])
def test_trigger_watch_handler_fires_for_video_files(monkeypatch, video_path):
    from app.services.watcher import _make_handler

    scheduled: list[str] = []
    _trap_run_coroutine_threadsafe(monkeypatch, scheduled)
    handler = _make_handler("t-watch", MagicMock())
    handler.on_created(MagicMock(is_directory=False, src_path=video_path))
    assert scheduled == ["fired"]


@pytest.mark.parametrize("non_video_path", [
    "/x/poster.jpg",
    "/x/fanart.jpg",
    "/x/landscape.jpg",
    "/x/logo.png",
    "/x/movie.nfo",
    "/x/movie.srt",
    "/x/Movie/Movie WEBDL-2160p.trickplay/320 - 10x10/0.jpg",
    "/x/movie.txt",
    "/x/no-extension",
    "/x/movie.mkv.partial",
])
def test_trigger_watch_handler_skips_non_video_files(monkeypatch, non_video_path):
    """The actual bug: the watcher's _Handler dispatched JPG/NFO/SRT events
    into the trigger pipeline, jamming the queue with garbage jobs."""
    from app.services.watcher import _make_handler

    scheduled: list[str] = []
    _trap_run_coroutine_threadsafe(monkeypatch, scheduled)
    handler = _make_handler("t-watch", MagicMock())
    handler.on_created(MagicMock(is_directory=False, src_path=non_video_path))
    assert scheduled == []


def test_trigger_watch_handler_skips_directory_events(monkeypatch):
    from app.services.watcher import _make_handler

    scheduled: list[str] = []
    _trap_run_coroutine_threadsafe(monkeypatch, scheduled)
    handler = _make_handler("t-watch", MagicMock())
    handler.on_created(MagicMock(is_directory=True, src_path="/x/new-movie-folder"))
    assert scheduled == []


@pytest.mark.asyncio
async def test_watcher_reads_from_triggers_table(monkeypatch, tmp_path):
    # tmp_path satisfies the new os.path.isdir guard that drops triggers
    # pointing at non-existent paths (so a misconfigured trigger doesn't
    # blow up the whole observer).
    fake_triggers = [
        type(
            "T",
            (),
            {
                "id": "t1",
                "type": "watch",
                "config": {"path": str(tmp_path)},
                "action": {"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
                "file_filter": {"type": "all", "value": None},
                "enabled": True,
            },
        )()
    ]
    monkeypatch.setattr(
        "app.services.watcher._load_watch_triggers",
        AsyncMock(return_value=fake_triggers),
    )
    started = []
    monkeypatch.setattr(
        "app.services.watcher._schedule_observer",
        lambda obs, path, handler: started.append(path),
    )
    obs = MagicMock()
    monkeypatch.setattr("app.services.watcher.PollingObserver", lambda timeout: obs)
    # Patch _subscribe_updates so it doesn't try to connect to Redis
    monkeypatch.setattr(
        "app.services.watcher.Watcher._subscribe_updates",
        AsyncMock(),
    )
    w = Watcher()
    await w.start()
    assert started == [str(tmp_path)]


# ---------------------------------------------------------------------------
# WS5 (2026-07 audit): file-size settle gate for watch triggers
# ---------------------------------------------------------------------------
import asyncio

from app.services.watcher import _wait_for_stable_size


def test_stable_file_passes_quickly(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x" * 1024)
    ok = asyncio.run(_wait_for_stable_size(str(f), probe_seconds=0.01, max_wait_seconds=1.0))
    assert ok is True


def test_growing_file_waits_then_gives_up(tmp_path):
    f = tmp_path / "movie.mkv"
    f.write_bytes(b"x")
    grow = {"n": 0}
    import app.services.watcher as w
    real_getsize = w.os.path.getsize

    def fake_getsize(path):
        grow["n"] += 1
        return grow["n"]  # size changes on every probe — never settles

    w_os_patch = fake_getsize
    orig = w.os.path.getsize
    w.os.path.getsize = w_os_patch
    try:
        ok = asyncio.run(_wait_for_stable_size(str(f), probe_seconds=0.01, max_wait_seconds=0.1))
    finally:
        w.os.path.getsize = orig
    assert ok is False


def test_vanished_file_returns_false(tmp_path):
    ok = asyncio.run(_wait_for_stable_size(str(tmp_path / "gone.mkv"),
                                           probe_seconds=0.01, max_wait_seconds=0.5))
    assert ok is False
