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

MAX_CHARS_PER_LINE = 42
MAX_LINES = 2
MAX_CUE_CHARS = MAX_CHARS_PER_LINE * MAX_LINES  # 84
MAX_CUE_DURATION = 7.0
MIN_CUE_DURATION = 1.0
MIN_READABLE_DURATION = 0.833  # Netflix minimum display time
MERGE_GAP_MAX = 0.5            # only merge across sub-half-second silences
MIN_GAP = 0.08
READING_SPEED_CPS = 17.0
PAUSE_SPLIT_SECONDS = 1.0
_SENTENCE_END = (".", "!", "?", "…")
_CLAUSE_BREAK = (",", ";", ":")
_CJK_TERMINATORS = "。！？"
_TRAILING_CLOSERS = ".!?…\"'”’)"
# Dots after these words are abbreviations, not sentence ends. Single-letter
# words ("U.S.A.", "p.m.") are handled separately in _is_sentence_end.
_ABBREVIATIONS = frozenset({
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "st", "vs", "etc",
    "gen", "col", "sgt", "lt", "capt", "no", "vol", "approx",
})

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
        s, e = float(start), float(end)
        out.append({"text": text, "start": min(s, e), "end": max(s, e)})
    out.sort(key=lambda w: (w["start"], w["end"]))
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
            # The gap to the next cue always wins — a too-short cue is the
            # merge step's problem; an overlapping one corrupts playback.
            end = min(end, out[i + 1]["start"] - min_gap)
        c["end"] = end
    return out


def apply_invariants(
    cues: list[dict],
    *,
    min_gap: float = MIN_GAP,
    min_duration: float = MIN_CUE_DURATION,
) -> list[dict]:
    """Final safety net before cues leave this module: sorted by start, strictly
    positive durations, and at least ``min_gap`` between consecutive cues.
    Overlaps are resolved by trimming the earlier cue; when the earlier cue has
    no room to trim, the two cues merge (text is never dropped)."""
    ordered = sorted(
        (dict(c) for c in cues if c["text"].strip()),
        key=lambda c: (c["start"], c["end"]),
    )
    out: list[dict] = []
    for c in ordered:
        if c["end"] <= c["start"]:
            c["end"] = c["start"] + min_duration
        if out:
            prev = out[-1]
            if c["start"] < prev["end"] + min_gap:
                trimmed = c["start"] - min_gap
                if trimmed > prev["start"]:
                    prev["end"] = trimmed
                else:
                    prev["text"] = f'{prev["text"]} {c["text"]}'.strip()
                    prev["end"] = max(prev["end"], c["end"])
                    continue
        out.append(c)
    return out


def _display_window(cues: list[dict], i: int, min_gap: float) -> float:
    """Display time cue i can possibly get, capped by the next cue's start."""
    c = cues[i]
    hard_end = c["end"]
    if i + 1 < len(cues):
        hard_end = min(hard_end, cues[i + 1]["start"] - min_gap)
    return hard_end - c["start"]


def merge_short_cues(
    cues: list[dict],
    *,
    min_duration: float = MIN_READABLE_DURATION,
    max_chars: int = MAX_CUE_CHARS,
    merge_gap: float = MERGE_GAP_MAX,
    min_gap: float = MIN_GAP,
) -> list[dict]:
    """Merge cues that cannot reach a readable display duration into the next
    cue, provided the silence between them is short and the combined text still
    fits one cue. Runs before ``enforce_timing`` so a trailing short cue with
    silence after it is left for the linger rule instead of merging."""
    out = [dict(c) for c in cues]
    i = 0
    while i < len(out):
        if _display_window(out, i, min_gap) >= min_duration or i + 1 >= len(out):
            i += 1
            continue
        nxt = out[i + 1]
        combined = f'{out[i]["text"]} {nxt["text"]}'.strip()
        if nxt["start"] - out[i]["end"] <= merge_gap and len(combined) <= max_chars:
            out[i] = {"text": combined, "start": out[i]["start"], "end": nxt["end"]}
            del out[i + 1]
            continue  # re-evaluate the merged cue
        i += 1
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


def _hard_chunks(token: str, max_chars: int) -> list[str]:
    """Slice a token with no usable word boundaries (CJK, URLs) into
    line-sized pieces."""
    return [token[i:i + max_chars] for i in range(0, len(token), max_chars)]


def _greedy_fill(words: list[str], max_chars: int) -> str:
    """Word-boundary greedy fill — the fallback when balanced wrapping can't
    fit. Tokens longer than a line are hard-broken so no output line ever
    exceeds ``max_chars``."""
    lines, cur = [], ""
    for w in words:
        for piece in (_hard_chunks(w, max_chars) if len(w) > max_chars else [w]):
            if cur and len(cur) + 1 + len(piece) > max_chars:
                lines.append(cur)
                cur = piece
            else:
                cur = f"{cur} {piece}".strip()
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
    """Index to split AFTER. Prefer a clause break nearest the middle, then a
    dominant pause, then the chars-balanced word boundary — never a split that
    would orphan a fragment shorter than 10 chars on either side."""
    total = len(" ".join(w["text"] for w in words))

    def left_len(i: int) -> int:
        return len(" ".join(w["text"] for w in words[: i + 1]))

    def side_ok(i: int) -> bool:
        return 10 <= left_len(i) <= total - 10

    def char_dist(i: int) -> float:
        return abs(left_len(i) - total / 2)

    ok = [i for i in range(len(words) - 1) if side_ok(i)]
    if not ok:
        ok = list(range(len(words) - 1)) or [0]
    clause = [i for i in ok if words[i]["text"].endswith(_CLAUSE_BREAK)]
    if clause:
        return min(clause, key=char_dist)
    gaps = sorted(words[i + 1]["start"] - words[i]["end"] for i in range(len(words) - 1))
    median_gap = gaps[len(gaps) // 2] if gaps else 0.0
    pause, pause_i = max(((words[i + 1]["start"] - words[i]["end"], i) for i in ok),
                         default=(0.0, ok[0]))
    if pause > max(3 * median_gap, 0.3):
        return pause_i
    return min(ok, key=char_dist)


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


def _split_point_text(words: list[str]) -> int:
    """Word index to split AFTER: clause break nearest the middle when both
    sides keep >= 10 chars, else the chars-balanced word boundary."""
    total = len(" ".join(words))

    def left_len(i: int) -> int:
        return len(" ".join(words[: i + 1]))

    def side_ok(i: int) -> bool:
        return 10 <= left_len(i) <= total - 10

    def char_dist(i: int) -> float:
        return abs(left_len(i) - total / 2)

    clause = [i for i, w in enumerate(words[:-1]) if w.endswith(_CLAUSE_BREAK) and side_ok(i)]
    if clause:
        return min(clause, key=char_dist)
    candidates = [i for i in range(len(words) - 1) if side_ok(i)] or list(range(len(words) - 1))
    return min(candidates, key=char_dist)


def split_long_cue_text(cue: dict, *, max_chars: int = MAX_CUE_CHARS) -> list[dict]:
    """Split a cue whose (translated or heuristic) text exceeds ``max_chars``
    into sub-cues at the clause/word boundary nearest the middle, distributing
    the time span proportionally to character share. Text-mode counterpart of
    ``split_long_sentence`` for paths that have no word timestamps."""
    text = cue["text"]
    if len(text) <= max_chars:
        return [cue]
    words = text.split()
    if len(words) < 2:  # no word boundaries (CJK / pathological token): hard-slice
        pieces = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
    else:
        b = _split_point_text(words)
        pieces = [" ".join(words[: b + 1]), " ".join(words[b + 1:])]
    span = cue["end"] - cue["start"]
    total = sum(len(p) for p in pieces)
    out: list[dict] = []
    cursor = cue["start"]
    for i, p in enumerate(pieces):
        is_last = i == len(pieces) - 1
        p_end = cue["end"] if is_last else cursor + span * (len(p) / total)
        out.extend(split_long_cue_text({"text": p, "start": cursor, "end": p_end},
                                       max_chars=max_chars))
        cursor = p_end
    return out


def _fit_lines(cue: dict) -> list[dict]:
    """Wrap a cue's text; when the wrap needs more than MAX_LINES lines (text
    within the char cap can still lack a word boundary for a 2x42 split), split
    the cue in time at the balanced word boundary and fit each half."""
    wrapped = wrap_lines(cue["text"])
    words = cue["text"].split()
    if wrapped.count("\n") + 1 <= MAX_LINES or len(words) < 2:
        return [dict(cue, text=wrapped)]
    b = _split_point_text(words)
    pieces = [" ".join(words[: b + 1]), " ".join(words[b + 1:])]
    span = cue["end"] - cue["start"]
    total = sum(len(p) for p in pieces)
    mid = cue["start"] + span * (len(pieces[0]) / total)
    first_end = max(cue["start"] + 1e-3, mid - MIN_GAP)
    return (_fit_lines({"text": pieces[0], "start": cue["start"], "end": first_end})
            + _fit_lines({"text": pieces[1], "start": mid, "end": cue["end"]}))


def _finalize(cues: list[dict]) -> list[dict]:
    """Shared tail of every path: merge unreadably-short cues, apply timing,
    enforce output invariants, wrap lines (splitting cues that cannot wrap
    within MAX_LINES)."""
    cues = merge_short_cues(cues)
    cues = enforce_timing(cues)
    cues = apply_invariants(cues)
    out: list[dict] = []
    for c in cues:
        out.extend(_fit_lines(c))
    return out


def format_cues(words: list[dict]) -> list[dict]:
    """Words -> final timed, wrapped source cues (no translation).

    Sentence-segment, split any over-long sentence on its source words, then
    apply the shared merge/timing/invariant/wrap chain."""
    cues: list[dict] = []
    for group in _group_words_by_cue(words):
        cues.extend(split_long_sentence(group))
    return _finalize(cues)


def _skip_closers(text: str, i: int) -> int:
    """First index after the terminator run starting at ``text[i]``."""
    j = i + 1
    while j < len(text) and text[j] in _TRAILING_CLOSERS:
        j += 1
    return j


def _word_before(text: str, i: int) -> str:
    """The alphabetic word immediately preceding index ``i``."""
    j = i
    while j > 0 and text[j - 1].isalpha():
        j -= 1
    return text[j:i]


def _is_abbreviation_dot(text: str, i: int) -> bool:
    """A dot after a known abbreviation or single letter ("Dr.", "U.S.A.")."""
    if text[i] != ".":
        return False
    word = _word_before(text, i)
    return bool(word) and (word.lower() in _ABBREVIATIONS or len(word) == 1)


def _is_sentence_end(text: str, i: int) -> bool:
    """True when the terminator at ``text[i]`` really ends a sentence — i.e. it
    is followed by whitespace + an uppercase/opening character, and a dot is not
    part of an abbreviation, initialism, or decimal number."""
    if text[i] in _CJK_TERMINATORS:
        return True
    j = _skip_closers(text, i)
    if j >= len(text):
        return True
    if not text[j].isspace():
        return False                      # "3.14", "e.g.x" — mid-token dot
    k = j
    while k < len(text) and text[k].isspace():
        k += 1
    if k >= len(text):
        return True
    opens_sentence = text[k].isupper() or text[k].isdigit() or text[k] in "\"'“‘¿¡-–—…♪"
    return opens_sentence and not _is_abbreviation_dot(text, i)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping terminators, without splitting inside
    abbreviations, initialisms, or decimal numbers. CJK terminators supported.
    Whitespace is trimmed; fragments with no alphanumeric content are dropped."""
    sentences: list[str] = []
    buf_start = 0
    i = 0
    while i < len(text):
        if (text[i] in _SENTENCE_END or text[i] in _CJK_TERMINATORS) and _is_sentence_end(text, i):
            j = i + 1
            while j < len(text) and text[j] in _TRAILING_CLOSERS:
                j += 1
            candidate = text[buf_start:j].strip()
            if any(ch.isalnum() for ch in candidate):
                sentences.append(candidate)
            buf_start = j
            i = j
            continue
        i += 1
    tail = text[buf_start:].strip()
    if tail and any(ch.isalnum() for ch in tail):
        sentences.append(tail)
    return sentences


def _distribute_segment(start: float, end: float, sentences: list[str]) -> list[dict]:
    """Spread one segment's [start, end] span across its sentences proportionally
    to character length. Cues are contiguous and non-overlapping; the last cue
    ends exactly at ``end`` so float drift never leaks past the segment."""
    total_chars = sum(len(s) for s in sentences)
    if total_chars == 0:
        return []
    span = end - start
    if span <= 0:
        # Garbage segment timing: synthesize a readable window per sentence and
        # let apply_invariants reconcile any collision with the next segment.
        end = start + MIN_CUE_DURATION * len(sentences)
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
    ``format_cues``). Over-long sentence cues are split on text before the
    shared merge/timing/invariant/wrap chain runs."""
    cues: list[dict] = []
    for c in segments_to_sentence_cues(segments):
        cues.extend(split_long_cue_text(c))
    return _finalize(cues)


def reflow_translated(cues: list[dict]) -> list[dict]:
    """Re-time, re-split, and re-wrap cues whose text was replaced by a
    translation.

    Timing is already source-derived, but translations routinely expand 20-30%,
    so text that no longer fits one cue is split (proportional timing) before
    the shared merge/timing/invariant/wrap chain re-applies reading-speed and
    line wrapping. Source line breaks are flattened first."""
    flat = [dict(c, text=" ".join(c["text"].splitlines())) for c in cues]
    out: list[dict] = []
    for c in flat:
        out.extend(split_long_cue_text(c))
    return _finalize(out)
