"""Shot-change-aware cue snapping (opt-in: SUBGEN_SHOT_SNAP=1).

Professional subtitles never let a cue boundary hover just off a picture
cut — the eye registers the mismatch as a flash. When enabled, one ffmpeg
scene-detection pass finds the cuts and cue boundaries within the snap
window move onto them (ends land two frames before the cut). Costs a full
video decode per job, hence opt-in.
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

SCENE_THRESHOLD = 0.3
SNAP_END_BEFORE_CUT = 0.5     # end this close BEFORE a cut extends to it
SNAP_END_AFTER_CUT = 0.3      # end this close AFTER a cut retracts to it
SNAP_START_WINDOW = 0.3       # start this close to a cut moves onto it
FRAME_SECONDS = 1.0 / 24.0
END_GUARD_FRAMES = 2          # ends land this many frames before the cut
MIN_SNAPPED_DURATION = 0.5    # never snap a cue below this duration

_PTS_RE = re.compile(r"pts_time:(\d+(?:\.\d+)?)")


def shot_snap_enabled() -> bool:
    return os.environ.get("SUBGEN_SHOT_SNAP", "").lower() in ("1", "true", "yes")


def parse_showinfo_times(stderr_text: str) -> list[float]:
    return [float(m.group(1)) for m in _PTS_RE.finditer(stderr_text)]


def detect_shot_changes(video_path: str) -> list[float] | None:
    """Cut timestamps via ffmpeg's scene filter, or None on any failure."""
    try:
        import ffmpeg

        _out, err = (
            ffmpeg
            .input(video_path)
            .filter("select", f"gt(scene,{SCENE_THRESHOLD})")
            .filter("showinfo")
            .output("pipe:", format="null")
            .run(capture_stdout=True, capture_stderr=True)
        )
        return parse_showinfo_times(err.decode("utf-8", errors="replace"))
    # snapping is polish, never fatal
    except Exception as exc:  # noqa: BLE001
        logger.warning("shot detection failed (%s: %s) — skipping snap",
                       type(exc).__name__, exc)
        return None


def _nearest(cuts: list[float], t: float) -> float | None:
    if not cuts:
        return None
    return min(cuts, key=lambda c: abs(c - t))


def _snap_start(start: float, cut: float | None) -> float:
    if cut is not None and abs(start - cut) <= SNAP_START_WINDOW:
        return cut
    return start


def _snap_end(end: float, cut: float | None) -> float:
    if cut is None:
        return end
    target = cut - END_GUARD_FRAMES * FRAME_SECONDS
    if 0 < cut - end <= SNAP_END_BEFORE_CUT or 0 <= end - cut <= SNAP_END_AFTER_CUT:
        return target
    return end


def snap_cues_to_shots(cues: list[dict], cuts: list[float]) -> list[dict]:
    """Move cue boundaries near picture cuts onto them. A snap that would
    squeeze a cue below MIN_SNAPPED_DURATION is reverted for that boundary."""
    if not cuts:
        return cues
    out = []
    for c in cues:
        start = _snap_start(c["start"], _nearest(cuts, c["start"]))
        end = _snap_end(c["end"], _nearest(cuts, c["end"]))
        if end - start < MIN_SNAPPED_DURATION:
            start, end = c["start"], c["end"]
        out.append(dict(c, start=start, end=end))
    return out
