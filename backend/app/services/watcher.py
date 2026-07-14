"""Watchdog file watcher service

Wraps `watchdog.observers.Observer` to monitor configured NAS folders and
auto-enqueue subtitle jobs for newly detected video files. The watchdog
runs in its own thread; detected paths are forwarded to the FastAPI event
loop via a thread-safe callback so all DB and Celery interactions stay
async.

The watcher keeps an in-memory ring buffer of recently skipped paths so the
WatchFolderPanel UI can display them without a dedicated DB table.

Automations: Adds a new async `Watcher` class that reads from the triggers
table and supports live-reload via a Redis pub/sub channel.
"""
import asyncio
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

import redis.asyncio as aioredis
from sqlalchemy import select
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from app.core.config import app_settings
from app.core.database import AsyncSessionLocal
from app.core.media import VIDEO_EXTENSIONS, is_video_file
from app.models.orm import Trigger

# NFS clients don't get inotify for remote writes; PollingObserver stats
# files instead, which works on any FS. 15s is plenty for movie folders
# (a real movie drop is followed by an hours-long transcribe) and is far
# easier on a NAS than 2s recursive stat-walks over thousands of files.
_NFS_POLL_INTERVAL_S = 15.0

# Bound `os.path.isdir` so a momentarily-unreachable NAS doesn't freeze
# lifespan startup (default NFS timeout is 60s+ per path).
_PATH_PROBE_TIMEOUT_S = 2.0

logger = logging.getLogger(__name__)

# Cap the in-memory ring buffer so a renamed-loop scenario can't exhaust
# memory. The UI shows the last 10; we hold a few more for slack.
_SKIPPED_BUFFER_SIZE = 32

OnDetected = Callable[[str], None]


def has_sibling_srt(video_path: str) -> bool:
    """Return True if a `<basename>.<lang>.srt` or `<basename>.srt` file
    sits next to the given video. Used to skip files that already have
    subtitles."""
    folder = os.path.dirname(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0]
    if not os.path.isdir(folder):
        return False
    for entry in os.listdir(folder):
        if not entry.lower().endswith(".srt"):
            continue
        entry_stem = os.path.splitext(entry)[0]
        if entry_stem == stem or entry_stem.startswith(f"{stem}."):
            return True
    return False


def _is_skipped_due_to_srt(path: str) -> bool:
    return is_video_file(path) and has_sibling_srt(path)


def should_enqueue(path: str) -> bool:
    """Decision combinator for the handler — exposed for unit tests."""
    if not is_video_file(path):
        return False
    if has_sibling_srt(path):
        logger.info("Skipped %s — SRT already exists", path)
        return False
    return True


class _VideoHandler(FileSystemEventHandler):
    """Routes FileCreatedEvent → enqueue callback after the eligibility
    check passes; falls through to the skipped recorder when an SRT is
    already present."""

    def __init__(self, on_detected: OnDetected, on_skipped: Callable[[str], None]) -> None:
        super().__init__()
        self._on_detected = on_detected
        self._on_skipped = on_skipped

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = str(event.src_path)
        if not is_video_file(path):
            return
        if has_sibling_srt(path):
            logger.info("Skipped %s — SRT already exists", path)
            self._on_skipped(path)
            return
        logger.info("Detected new video: %s", path)
        self._on_detected(path)


class WatcherService:
    """Single shared observer over all configured watch folders.

    Thread-safe restart: calling `restart` stops and recreates the observer
    so settings can be hot-reloaded without an app-level restart.
    """

    def __init__(self, on_detected: OnDetected) -> None:
        self._on_detected = on_detected
        self._observer: Optional[Observer] = None
        self._paths: tuple[str, ...] = ()
        # (path, ISO-8601 timestamp) tuples; bounded ring buffer.
        self._skipped: deque[tuple[str, str]] = deque(maxlen=_SKIPPED_BUFFER_SIZE)
        self._skipped_lock = threading.Lock()

    def _record_skipped(self, path: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self._skipped_lock:
            self._skipped.append((path, ts))

    def recent_skipped(self, limit: int = 10) -> list[dict]:
        with self._skipped_lock:
            entries = list(self._skipped)
        # Most recent first
        entries.reverse()
        return [{"path": p, "skipped_at": ts} for p, ts in entries[:limit]]

    @property
    def paths(self) -> tuple[str, ...]:
        return self._paths

    def start(self, paths: Iterable[str]) -> None:
        cleaned = tuple(p for p in paths if p)
        if self._observer is not None:
            return  # already running — caller should use restart
        if not cleaned:
            logger.info("Watcher start skipped — no watch folders configured")
            self._paths = ()
            return

        observer = Observer()
        handler = _VideoHandler(self._on_detected, self._record_skipped)
        scheduled: list[str] = []
        for path in cleaned:
            if not os.path.isdir(path):
                logger.warning("Watch folder does not exist, skipping: %s", path)
                continue
            observer.schedule(handler, path, recursive=False)
            logger.info("Monitoring watch folder: %s", path)
            scheduled.append(path)

        observer.start()
        self._observer = observer
        self._paths = tuple(scheduled)

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._observer = None
        self._paths = ()

    def restart(self, paths: Iterable[str]) -> None:
        self.stop()
        self.start(paths)


# ---------------------------------------------------------------------------
# Trigger-based async Watcher (Automations feature)
# ---------------------------------------------------------------------------


async def _load_watch_triggers() -> list[Trigger]:
    """Load all enabled watch triggers from the DB."""
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Trigger).where(
                    Trigger.type == "watch", Trigger.enabled.is_(True)
                )
            )
        ).scalars().all()
        return list(rows)


def _schedule_observer(observer, path: str, handler) -> None:
    observer.schedule(handler, path, recursive=True)


def _make_handler(trigger_id: str, loop: asyncio.AbstractEventLoop):
    """Return a watchdog FileSystemEventHandler that fires MatchEvent via the given loop."""
    # Import here to avoid circular imports at module level
    from app.services.trigger_executor import MatchEvent, dispatch_event

    class _Handler(FileSystemEventHandler):
        def on_created(self, event) -> None:
            if event.is_directory:
                return
            path = str(event.src_path)
            # Hot-path pre-filter — a movie-folder drop fires this handler
            # once per sidecar (jpg/nfo/srt) so we skip the cross-thread
            # asyncio + DB write before dispatch_event would skip them anyway.
            if not is_video_file(path):
                return
            asyncio.run_coroutine_threadsafe(
                _fire(trigger_id, path, "created"), loop
            )

    return _Handler()


# A created event fires the moment the copy STARTS; transcribing a half-copied
# file "completes" with subtitles for a fraction of the movie. Wait for the
# size to hold still across a probe interval before dispatching.
_SETTLE_PROBE_SECONDS = 10.0
_SETTLE_MAX_WAIT_SECONDS = 1800.0


async def _wait_for_stable_size(
    path: str,
    *,
    probe_seconds: float = _SETTLE_PROBE_SECONDS,
    max_wait_seconds: float = _SETTLE_MAX_WAIT_SECONDS,
) -> bool:
    """True once the file's size holds still across one probe interval; False
    when it vanishes or is still growing after ``max_wait_seconds``."""
    deadline = time.monotonic() + max_wait_seconds
    last_size = -1
    while time.monotonic() < deadline:
        try:
            size = await asyncio.to_thread(os.path.getsize, path)
        except OSError:
            return False  # vanished / unreadable mid-copy
        if size == last_size and size > 0:
            return True
        last_size = size
        await asyncio.sleep(probe_seconds)
    return False


async def _fire(trigger_id: str, path: str, event_type: str) -> None:
    from app.services.trigger_executor import MatchEvent, dispatch_event

    if not await _wait_for_stable_size(path):
        logger.warning(
            "Watch trigger %s: %s never size-settled (still copying or gone) — "
            "not dispatching; a scheduled scan will pick it up once complete",
            trigger_id, path,
        )
        return

    async with AsyncSessionLocal() as session:
        await dispatch_event(
            session,
            MatchEvent(
                trigger_id=trigger_id,
                file_path=path,
                source_payload={"original_event_type": event_type},
            ),
        )


class Watcher:
    """Async trigger-table-based file watcher with live-reload via Redis pub/sub."""

    def __init__(self) -> None:
        self._observer: Optional[Observer] = None
        self._sub_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        await self._reload()
        self._sub_task = asyncio.create_task(self._subscribe_updates())

    async def _reload(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None

        triggers = await _load_watch_triggers()
        observer = PollingObserver(timeout=_NFS_POLL_INTERVAL_S)
        loop = asyncio.get_running_loop()
        for t in triggers:
            path = t.config.get("path", "")
            if not path:
                continue
            try:
                exists = await asyncio.wait_for(
                    asyncio.to_thread(os.path.isdir, path),
                    timeout=_PATH_PROBE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning("Watch trigger %s: path probe timed out (NAS slow?), skipping: %s", t.id, path)
                continue
            if not exists:
                logger.warning("Watch trigger %s: path does not exist, skipping: %s", t.id, path)
                continue
            handler = _make_handler(t.id, loop)
            _schedule_observer(observer, path, handler)
            logger.debug("Watching trigger %s on %s", t.id, path)
        observer.start()
        self._observer = observer

    async def _subscribe_updates(self) -> None:
        from app.services.trigger_service import TRIGGER_UPDATES_CHANNEL

        r = aioredis.from_url(app_settings.redis_url)
        pubsub = r.pubsub()
        await pubsub.subscribe(TRIGGER_UPDATES_CHANNEL)
        try:
            while True:
                msg = await pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=5
                )
                if msg is None:
                    continue
                await self._reload()
        finally:
            await pubsub.aclose()
            await r.aclose()

    def stop(self) -> None:
        if self._sub_task is not None:
            self._sub_task.cancel()
            self._sub_task = None
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
