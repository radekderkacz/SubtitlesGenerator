"""Audio↔subtitle synchronization self-check.

Correlates the subtitle on-screen pattern against the VAD speech pattern
(both as 100 ms speech/no-speech bins, ffsubsync-style FFT cross-correlation).
Subtitles generated from the same audio should peak at offset ~0; a large
offset means a container start-time bug, wrong audio track, or timing-math
regression. Pure numpy; every failure degrades to "no information".
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BIN_SECONDS = 0.1
MAX_OFFSET_SECONDS = 30.0
SYNC_WARN_SECONDS = 1.5
SYNC_FAIL_SECONDS = 5.0
# Correlation quality floor: below this overlap the "best offset" is noise.
MIN_OVERLAP_BINS = 50


def _to_bins(intervals: list[tuple[float, float]], n_bins: int):
    import numpy as np

    arr = np.zeros(n_bins, dtype=np.float32)
    for start, end in intervals:
        lo = max(0, int(start / BIN_SECONDS))
        hi = min(n_bins, int(end / BIN_SECONDS) + 1)
        if hi > lo:
            arr[lo:hi] = 1.0
    return arr


def subtitle_speech_offset(
    cues: list[dict], regions: list[tuple[float, float]]
) -> float | None:
    """Best time offset (seconds, positive = subtitles LATE relative to
    speech) within ±MAX_OFFSET_SECONDS, or None when undeterminable."""
    try:
        import numpy as np
    except ImportError:
        return None
    if not cues or not regions:
        return None
    cue_iv = [(c["start"], c["end"]) for c in cues if c["end"] > c["start"]]
    if not cue_iv:
        return None
    horizon = max(max(e for _s, e in cue_iv), max(e for _s, e in regions))
    n_bins = int(horizon / BIN_SECONDS) + 1
    if n_bins < MIN_OVERLAP_BINS:
        return None
    a = _to_bins(cue_iv, n_bins)      # subtitles
    b = _to_bins(list(regions), n_bins)  # speech
    if a.sum() < MIN_OVERLAP_BINS or b.sum() < MIN_OVERLAP_BINS:
        return None
    a -= a.mean()
    b -= b.mean()
    size = 1
    while size < 2 * n_bins:
        size *= 2
    fa = np.fft.rfft(a, size)
    fb = np.fft.rfft(b, size)
    corr = np.fft.irfft(fa * np.conj(fb), size)
    max_shift = int(MAX_OFFSET_SECONDS / BIN_SECONDS)
    # corr[k] = correlation of subtitles shifted LEFT by k (subs late by +k)
    forward = corr[: max_shift + 1]           # subtitles late
    backward = corr[-max_shift:][::-1]        # subtitles early
    best_fwd = int(np.argmax(forward))
    best_bwd = int(np.argmax(backward)) + 1
    if forward[best_fwd] >= backward[best_bwd - 1]:
        return best_fwd * BIN_SECONDS
    return -best_bwd * BIN_SECONDS


def sync_check(cues: list[dict], regions: list[tuple[float, float]] | None) -> dict:
    """Verification Check: measured subtitle↔speech offset."""
    name = "av_sync"
    if not regions:
        return {"layer": "heuristic", "name": name, "severity": "ok",
                "detail": "no speech-region data for this job"}
    offset = subtitle_speech_offset(cues, regions)
    if offset is None:
        return {"layer": "heuristic", "name": name, "severity": "ok",
                "detail": "sync check inconclusive"}
    detail = f"subtitles offset {offset:+.1f}s vs detected speech"
    if abs(offset) >= SYNC_FAIL_SECONDS:
        return {"layer": "heuristic", "name": name, "severity": "fail", "detail": detail}
    if abs(offset) >= SYNC_WARN_SECONDS:
        return {"layer": "heuristic", "name": name, "severity": "warn", "detail": detail}
    return {"layer": "heuristic", "name": name, "severity": "ok", "detail": detail}
