"""Pure subtitle-cue timing helpers. No I/O, no worker imports.

Re-segments and re-times subtitle cues so they line up with speech instead of
dumping a whole multi-sentence Whisper segment on screen at once. Two source
paths feed the same timing/wrapping rules:

- word path  — when the transcription backend returns word-level timestamps,
  ``format_cues`` regroups words into sentence cues.
- heuristic  — the live server is segment-only, so ``segments_to_sentence_cues``
  splits each segment's text into sentences and distributes the segment's
  ``[start, end]`` span across them proportionally to character length.

See ``docs/superpowers/specs/2026-06-17-subtitle-timing-design.md``.
"""
from __future__ import annotations

import re

MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CUE_CHARS = MAX_CHARS_PER_LINE * MAX_LINES  # 84
MAX_CUE_DURATION = 7.0
MIN_CUE_DURATION = 1.0
MIN_GAP = 0.08
READING_SPEED_CPS = 17.0
PAUSE_SPLIT_SECONDS = 1.0
_SENTENCE_END = (".", "!", "?", "…")
_CLAUSE_BREAK = (",", ";", ":")
# A sentence = a run of non-terminator chars followed by any trailing
# terminators. Requires at least one non-terminator, so a pure-punctuation
# fragment (e.g. "...") yields no sentence.
_SENTENCE_RE = re.compile(r"[^.!?…]+[.!?…]*")

# Both Word and Cue are normalized dicts with three keys: a stripped "text"
# string plus float "start" and "end" times in seconds.


def extract_words(response: dict) -> list[dict]:
    """Normalize a verbose_json transcription response to a flat word list.

    Handles both shapes a word-capable server may return: a top-level
    ``words`` array, or ``words`` nested under each segment. Tokens are
    stripped of the leading space Whisper emits; empty tokens and tokens
    without finite start/end are dropped. The live segment-only server has no
    ``words`` anywhere, so this returns ``[]`` and the heuristic path runs.
    """
    raw: list[dict] = []
    if isinstance(response.get("words"), list):
        raw = response["words"]
    else:
        for seg in response.get("segments") or []:
            if isinstance(seg.get("words"), list):
                raw.extend(seg["words"])

    out: list[dict] = []
    for w in raw:
        text = w.get("word") if w.get("word") is not None else (w.get("text") or "")
        text = text.strip()
        start, end = w.get("start"), w.get("end")
        if not text or start is None or end is None:
            continue
        out.append({"text": text, "start": float(start), "end": float(end)})
    return out


def _cue_from(words: list[dict]) -> dict:
    return {
        "text": " ".join(w["text"] for w in words),
        "start": words[0]["start"],
        "end": words[-1]["end"],
    }


def _group_words_by_cue(
    words: list[dict],
    *,
    max_chars: int = MAX_CUE_CHARS,
    max_duration: float = MAX_CUE_DURATION,
    pause_split: float = PAUSE_SPLIT_SECONDS,
) -> list[list[dict]]:
    """Group words into per-cue runs, breaking at sentence ends, long pauses,
    and char/duration caps. Returns the word groups so callers that need the
    underlying words (e.g. long-sentence splitting) can reuse them."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            projected_chars = len(" ".join(x["text"] for x in cur)) + 1 + len(w["text"])
            projected_dur = w["end"] - cur[0]["start"]
            if gap > pause_split or projected_chars > max_chars or projected_dur > max_duration:
                groups.append(cur)
                cur = []
        cur.append(w)
        if w["text"].endswith(_SENTENCE_END):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def words_to_cues(
    words: list[dict],
    *,
    max_chars: int = MAX_CUE_CHARS,
    max_duration: float = MAX_CUE_DURATION,
    pause_split: float = PAUSE_SPLIT_SECONDS,
) -> list[dict]:
    """Group words into cues, breaking at sentence ends, long pauses, and
    char/duration caps. Each cue's times come straight from its words."""
    return [
        _cue_from(g)
        for g in _group_words_by_cue(
            words, max_chars=max_chars, max_duration=max_duration, pause_split=pause_split
        )
    ]


def enforce_timing(
    cues: list[dict],
    *,
    min_duration: float = MIN_CUE_DURATION,
    max_duration: float = MAX_CUE_DURATION,
    min_gap: float = MIN_GAP,
    cps: float = READING_SPEED_CPS,
) -> list[dict]:
    """Apply reading-speed/duration/gap rules. Lingers a cue into the silence
    after speech (end = max(last_word_end, start + chars/cps)) but never past
    the next cue's start minus the gap, nor past start + max_duration."""
    out = [dict(c) for c in cues]
    for i, c in enumerate(out):
        readable = c["start"] + len(c["text"]) / cps
        end = max(c["end"], readable)
        end = min(end, c["start"] + max_duration)
        end = max(end, c["start"] + min_duration)
        if i + 1 < len(out):
            ceiling = out[i + 1]["start"] - min_gap
            if ceiling > c["start"]:
                end = min(end, ceiling)
        c["end"] = end
    return out


def _balanced_two_line_split(words: list[str], max_chars: int) -> str | None:
    """Split into two lines at the point minimizing the longer line, with both
    lines within max_chars. Returns the wrapped text, or None if no such split."""
    best_split, best_metric = None, None
    for i in range(1, len(words)):
        top, bottom = " ".join(words[:i]), " ".join(words[i:])
        if len(top) > max_chars or len(bottom) > max_chars:
            continue
        metric = max(len(top), len(bottom))
        if best_metric is None or metric < best_metric:
            best_split, best_metric = i, metric
    if best_split is None:
        return None
    return " ".join(words[:best_split]) + "\n" + " ".join(words[best_split:])


def _greedy_fill(words: list[str], max_chars: int) -> str:
    """Word-boundary greedy fill — the fallback when balanced wrapping can't fit."""
    lines, cur = [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > max_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def wrap_lines(text: str, *, max_chars: int = MAX_CHARS_PER_LINE, max_lines: int = MAX_LINES) -> str:
    """Wrap at word boundaries into up to max_lines balanced lines. For two
    lines, choose the split point that minimizes the longer line."""
    if len(text) <= max_chars:
        return text
    words = text.split()
    if max_lines == 2:
        balanced = _balanced_two_line_split(words, max_chars)
        if balanced is not None:
            return balanced
    return _greedy_fill(words, max_chars)


def _too_big(words: list[dict], max_chars: int, max_duration: float) -> bool:
    text_len = len(" ".join(w["text"] for w in words))
    return text_len > max_chars or (words[-1]["end"] - words[0]["start"]) > max_duration


def _best_break(words: list[dict]) -> int:
    """Index to split AFTER. Prefer a clause break nearest the middle; else the
    largest inter-word pause; else the middle."""
    mid = len(words) / 2
    clause = [i for i, w in enumerate(words[:-1]) if w["text"].endswith(_CLAUSE_BREAK)]
    if clause:
        return min(clause, key=lambda i: abs(i - mid))
    if len(words) > 2:
        gaps = [(words[i + 1]["start"] - words[i]["end"], i) for i in range(len(words) - 1)]
        return max(gaps)[1]
    return len(words) // 2 - 1 if len(words) > 1 else 0


def split_long_sentence(
    words: list[dict],
    *,
    max_chars: int = MAX_CUE_CHARS,
    max_duration: float = MAX_CUE_DURATION,
) -> list[dict]:
    """Recursively split an over-long sentence's words into cues under caps.

    Operates on the cue's source words (before translation), so every resulting
    sub-cue is later translated independently and inherits real timing — no
    translated-text splitting is ever needed."""
    if not words:
        return []
    if not _too_big(words, max_chars, max_duration) or len(words) == 1:
        return [_cue_from(words)]
    b = _best_break(words)
    left, right = words[: b + 1], words[b + 1:]
    if not left or not right:                       # degenerate — bail to a single cue
        return [_cue_from(words)]
    return (split_long_sentence(left, max_chars=max_chars, max_duration=max_duration)
            + split_long_sentence(right, max_chars=max_chars, max_duration=max_duration))


def format_cues(words: list[dict]) -> list[dict]:
    """Words -> final timed, wrapped source cues (no translation).

    Sentence-segment, split any over-long sentence on its source words, then
    apply reading-speed/duration/gap timing and line wrapping."""
    cues: list[dict] = []
    for group in _group_words_by_cue(words):
        cues.extend(split_long_sentence(group))
    cues = enforce_timing(cues)
    for c in cues:
        c["text"] = wrap_lines(c["text"])
    return cues


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on .!?… , keeping the terminator. Whitespace is
    trimmed and empty / pure-punctuation fragments are dropped."""
    return [m.group().strip() for m in _SENTENCE_RE.finditer(text) if m.group().strip()]


def _distribute_segment(start: float, end: float, sentences: list[str]) -> list[dict]:
    """Spread one segment's [start, end] span across its sentences proportionally
    to character length. Cues are contiguous and non-overlapping; the last cue
    ends exactly at ``end`` so float drift never leaks past the segment."""
    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        return []
    span = end - start
    cues: list[dict] = []
    cursor = start
    for i, sentence in enumerate(sentences):
        is_last = i == len(sentences) - 1
        s_end = end if is_last else cursor + span * (len(sentence) / total_chars)
        cues.append({"text": sentence, "start": cursor, "end": s_end})
        cursor = s_end
    return cues


def segments_to_sentence_cues(segments: list[dict]) -> list[dict]:
    """Heuristic re-segmentation for a segment-only transcription backend.

    Splits each segment's text into sentences and distributes the segment's
    time span across them proportionally to length. Approximate (assumes a
    roughly constant speech rate within a segment) but removes the
    all-sentences-on-screen-at-once symptom with today's segment-level data."""
    cues: list[dict] = []
    for seg in segments:
        text = (seg.get("text") or "").strip()
        start, end = seg.get("start"), seg.get("end")
        if not text or start is None or end is None:
            continue
        cues.extend(_distribute_segment(float(start), float(end), _split_sentences(text)))
    return cues


def format_cues_from_segments(segments: list[dict]) -> list[dict]:
    """Segment-only path -> final timed, wrapped cues (heuristic counterpart of
    ``format_cues``). Same reading-speed/duration/gap + line-wrap rules."""
    cues = enforce_timing(segments_to_sentence_cues(segments))
    for c in cues:
        c["text"] = wrap_lines(c["text"])
    return cues


def reflow_translated(cues: list[dict]) -> list[dict]:
    """Re-time and re-wrap cues whose text was replaced by a translation.

    Timing is already source-derived; translated text differs in length, so
    reading-speed and line wrapping are re-applied. Any line breaks carried over
    from the source wrapping are flattened first so the target wraps cleanly."""
    cues = enforce_timing(cues)
    for c in cues:
        c["text"] = wrap_lines(" ".join(c["text"].splitlines()))
    return cues
