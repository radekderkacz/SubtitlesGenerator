"""Shared media-file constants + helpers.

Single source of truth for "is this a video file". Previously `VIDEO_EXTENSIONS`
was duplicated in `services/file_browser.py` and `services/watcher.py`; the
Automations cron-scan + manual-fire loops then walked every file with no video
gate at all, submitting `.srt`/`.jpg`/`.nfo` sidecars as transcription jobs.
Everything now imports from here.
"""
import os

# Container/extension set the app treats as transcribable video.
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mkv", ".mp4", ".avi", ".m4v", ".mov"}
)


def is_video_file(path: str) -> bool:
    """True if `path` has a recognised video extension (case-insensitive)."""
    return os.path.splitext(path)[1].lower() in VIDEO_EXTENSIONS
