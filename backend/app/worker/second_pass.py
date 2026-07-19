"""Targeted second-pass recovery of faint dialogue.

VAD hears speech; Whisper produced nothing there. Those spans — phone
calls, whispers, dialogue buried under music — get a second attempt:
each gap is re-extracted with aggressive speech enhancement (strong
expansion, telephone-band EQ, denoise) and re-transcribed on its own,
where Whisper's per-window normalization can focus on the quiet signal
instead of being dominated by the loud scenes around it.

Pure functions only; the orchestration (ffmpeg + API calls) lives in
tasks.py next to the rest of the pipeline I/O.
"""
from __future__ import annotations

MIN_GAP_SECONDS = 2.0
MAX_GAPS = 8
CLIP_PAD_SECONDS = 0.3

# Stronger than the global extraction speechnorm (e=25 vs 12.5): these spans
# already failed once, and the band-pass + denoiser keep the expansion from
# amplifying rumble/hiss instead of the voice.
ENHANCE_FILTER = "speechnorm=e=25:r=0.0001:l=1,highpass=f=200,lowpass=f=3800,afftdn"


def _subtract_spans(
    region: tuple[float, float], spans: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sub-intervals of one region not covered by any span (spans sorted)."""
    out: list[tuple[float, float]] = []
    cursor, r_end = float(region[0]), float(region[1])
    for s_start, s_end in spans:
        if s_end <= cursor:
            continue
        if s_start >= r_end:
            break
        if s_start > cursor:
            out.append((cursor, min(s_start, r_end)))
        cursor = max(cursor, s_end)
        if cursor >= r_end:
            break
    if cursor < r_end:
        out.append((cursor, r_end))
    return out


def find_speech_gaps(
    speech_regions: list[tuple[float, float]] | None,
    segments: list[dict],
    *,
    min_gap: float = MIN_GAP_SECONDS,
    max_gaps: int = MAX_GAPS,
) -> list[tuple[float, float]]:
    """Sub-intervals of VAD speech with no overlapping transcribed segment.

    Subtracts every segment's [start, end) from every speech region and keeps
    remainders of at least ``min_gap`` seconds, longest first, capped at
    ``max_gaps`` (then re-sorted chronologically)."""
    if not speech_regions:
        return []
    spans = sorted(
        (float(s["start"]), float(s["end"]))
        for s in segments
        if s.get("start") is not None and s.get("end") is not None
    )
    gaps = [g for region in speech_regions for g in _subtract_spans(region, spans)]
    gaps = [(a, b) for a, b in gaps if b - a >= min_gap]
    gaps.sort(key=lambda g: g[0] - g[1])  # longest first
    return sorted(gaps[:max_gaps])


def merge_recovered(
    segments: list[dict], recovered: list[dict],
) -> list[dict]:
    """Merge recovered segments into the main list, chronologically. Recovered
    segments that would land inside an existing segment's span are dropped —
    the first pass already covered that time."""
    def overlaps_existing(seg: dict) -> bool:
        s, e = float(seg["start"]), float(seg["end"])
        mid = (s + e) / 2
        return any(float(x["start"]) <= mid < float(x["end"]) for x in segments)

    fresh = [r for r in recovered
             if (r.get("text") or "").strip() and not overlaps_existing(r)]
    return sorted(segments + fresh, key=lambda s: float(s["start"]))


def offset_segments(segments: list[dict], offset: float) -> list[dict]:
    """Shift clip-relative timestamps back onto the full-file timeline."""
    return [{**s, "start": float(s["start"]) + offset, "end": float(s["end"]) + offset}
            for s in segments
            if s.get("start") is not None and s.get("end") is not None]
