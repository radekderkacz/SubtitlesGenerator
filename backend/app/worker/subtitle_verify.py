"""Pure subtitle-verification checks. No I/O, no worker imports.

Mirrors cue_timing.py: deterministic, table-testable helpers. The LLM judge
(the only I/O) lives in subtitle_verify_judge.py and is composed in by verify().
"""
from __future__ import annotations

import json
import re

MAX_CHARS_PER_LINE = 42
# Identical-consecutive-cue run length, tiered from real data: across a corpus
# of normal subtitles, runs of ~10-24 are common and usually legitimate
# (repeated short utterances, sound cues, backchanneling) so they only WARN;
# genuine hallucination loops run far longer (30-100+), so only those FAIL.
# Below the warn line is treated as normal.
REPEAT_RUN_WARN = 12
REPEAT_RUN_FAIL = 30
SHORT_REPEAT_RUN_WARN = 25
SHORT_REPEAT_RUN_FAIL = 45
SHORT_LINE_MAX_WORDS = 2
COVERAGE_MIN_RATIO = 0.5
MIN_CUES = 1
# Overlapping cues are a soft signal — enforce_timing deliberately allows a few
# sub-second overlaps in tightly-packed runs. Only warn when MORE than this
# fraction of cues overlap (a systemic timing issue), not on the odd one.
OVERLAP_WARN_FRACTION = 0.01
# Per-cue reading-speed ceiling. 35 (not the comfortable ~17) flags only
# genuinely rushed cues; a handful are unavoidable (enforce_timing packs tight
# runs), so reading_speed only warns when MORE than CPS_WARN_FRACTION of cues
# exceed it — i.e. a systemic problem, not the odd dense line. Real data: clean
# sources sit ~0%, dense translations ~3%, both below the 5% gate.
CPS_MAX = 35.0
CPS_WARN_FRACTION = 0.05
GAP_WARN_SECONDS = 90.0     # silent gaps shorter than this are normal (scene/music)
SAMPLE_CUES = 25
# Credit-reel phrases that warn ANYWHERE in the file (near-certain artifacts).
STRONG_ARTIFACT_PHRASES = (
    "thanks for watching", "subtitles by", "amara.org", ".com/sub",
)
# Phrases that occur in legitimate dialogue ("I subscribe to that newspaper");
# they only warn when the cue is essentially nothing but the phrase AND sits
# near the edges of the subtitle span (Whisper's credits-hallucination habitat).
WEAK_ARTIFACT_PHRASES = ("subscribe", "www.")
WEAK_ARTIFACT_EDGE_SECONDS = 120.0
WEAK_ARTIFACT_COVERAGE = 0.6
# Kept for backwards compatibility with external callers/tests.
ARTIFACT_PHRASES = STRONG_ARTIFACT_PHRASES + WEAK_ARTIFACT_PHRASES
# Small-vocabulary stretches catch cyclic hallucination loops (A-B-A-B,
# three-cycles) that defeat the identical-consecutive run detector: any
# stretch of consecutive cues drawing on <= LOOP_DISTINCT_MAX distinct
# normalized texts is suspicious once it is long enough.
LOOP_DISTINCT_MAX = 3
LOOP_WARN_LEN = 25
LOOP_FAIL_LEN = 45
BLANK_WARN_FRACTION = 0.02
BLANK_FAIL_FRACTION = 0.10
# Coverage upper bound: subtitles extending well past the video's end mean
# broken timing (or the wrong video), not just credits spillover.
COVERAGE_OVER_WARN = 1.1
COVERAGE_OVER_FAIL = 1.5
# source<->target alignment bounds (translated jobs). Loose on purpose:
# reflow_translated legitimately splits expanded translations into more cues.
ALIGN_COUNT_OK = (0.8, 1.6)
ALIGN_COUNT_HARD = (0.5, 2.5)
ALIGN_CHARS_OK = (0.6, 2.2)
ALIGN_CHARS_HARD_LOW = 0.35
LINE_LENGTH_LIMIT = 45
LINE_LENGTH_WARN_FRACTION = 0.05

# A Check is a dict with keys: layer (structural / heuristic / semantic), name,
# severity (ok / warn / fail), and a human-readable detail string. A Cue is a
# dict with keys: index (int), start and end (floats, seconds), and text (str).

_TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def _ts_to_sec(ts: str) -> float | None:
    m = _TS.match(ts.strip())
    if not m:
        return None
    h, mnt, s, ms = (int(g) for g in m.groups())
    return h * 3600 + mnt * 60 + s + ms / 1000


def parse_srt(text: str) -> list[dict]:
    """Tolerant SRT parser -> list of {index,start,end,text}. Skips malformed
    blocks rather than raising (we are verifying possibly-bad output)."""
    cues: list[dict] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.splitlines()
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        try:
            idx = int(lines[0].strip())
        except ValueError:
            idx = len(cues) + 1
        start_s, _, end_s = lines[1].partition("-->")
        start, end = _ts_to_sec(start_s), _ts_to_sec(end_s)
        if start is None or end is None:
            continue
        cues.append({"index": idx, "start": start, "end": end, "text": "\n".join(lines[2:]).strip()})
    return cues


def _ok(layer, name, detail=""):
    return {"layer": layer, "name": name, "severity": "ok", "detail": detail}


def _coverage_severity(ratio: float) -> str:
    if ratio >= COVERAGE_MIN_RATIO:
        return "ok"
    if ratio >= 0.2:
        return "warn"
    return "fail"


def _check_overlap(cues: list[dict]) -> dict:
    # Overlaps are a soft signal, not "broken": enforce_timing deliberately
    # permits sub-second overlaps in tightly-packed cue runs to keep each cue on
    # screen for the minimum readable duration. Only warn when a systemic share
    # overlap — a single one is normal, not worth flagging.
    overlaps = [b["index"] for a, b in zip(cues, cues[1:]) if b["start"] < a["end"]]
    # 1-2 overlaps are never "systemic" (tight-packing); above that, scale by size.
    too_many = len(overlaps) > max(2, OVERLAP_WARN_FRACTION * len(cues))
    return {"layer": "structural", "name": "no_overlap",
            "severity": "warn" if too_many else "ok",
            "detail": f"{len(overlaps)} overlapping cues: {overlaps[:5]}" if overlaps else ""}


def _check_monotonic(cues: list[dict]) -> dict:
    out_of_order = sum(1 for a, b in zip(cues, cues[1:]) if b["start"] < a["start"])
    return {"layer": "structural", "name": "monotonic_order",
            "severity": "warn" if out_of_order else "ok",
            "detail": f"{out_of_order} cue(s) start before their predecessor"
            if out_of_order else ""}


def _check_coverage(cues: list[dict], video_duration: float) -> dict:
    ratio = max(c["end"] for c in cues) / video_duration
    if ratio > COVERAGE_OVER_FAIL:
        sev, note = "fail", "subtitles extend far past the video's end"
    elif ratio > COVERAGE_OVER_WARN:
        sev, note = "warn", "subtitles extend past the video's end"
    else:
        sev, note = _coverage_severity(ratio), ""
    detail = f"subtitles cover {ratio*100:.0f}% of runtime"
    return {"layer": "structural", "name": "coverage", "severity": sev,
            "detail": f"{detail} — {note}" if note else detail}


def check_structural(srt_text: str, video_duration: float | None) -> list[dict]:
    checks: list[dict] = []
    if not srt_text.strip():
        return [{"layer": "structural", "name": "non_empty", "severity": "fail",
                 "detail": "SRT file is empty"}]
    checks.append(_ok("structural", "non_empty"))

    cues = parse_srt(srt_text)
    if len(cues) < MIN_CUES:
        checks.append({"layer": "structural", "name": "min_cues", "severity": "fail",
                       "detail": f"parsed {len(cues)} cues"})
        return checks
    checks.append(_ok("structural", "min_cues", f"{len(cues)} cues"))

    inverted = [c["index"] for c in cues if c["end"] <= c["start"]]
    checks.append({"layer": "structural", "name": "start_before_end",
                   "severity": "fail" if inverted else "ok",
                   "detail": f"inverted cues: {inverted[:5]}" if inverted else ""})

    checks.append(_check_overlap(cues))
    checks.append(_check_monotonic(cues))
    if video_duration and video_duration > 0:
        checks.append(_check_coverage(cues, video_duration))
    return checks


def check_alignment(cues: list[dict], source_cues: list[dict]) -> list[dict]:
    """Source↔target sanity for translated jobs: a translation should have
    roughly the source's cue count and text volume. Catches dropped batches
    and runaway splits that per-file checks can't see."""
    if not cues or not source_cues:
        return []
    count_ratio = len(cues) / len(source_cues)
    tgt_chars = sum(len(_norm_text(c["text"])) for c in cues) or 1
    src_chars = sum(len(_norm_text(c["text"])) for c in source_cues) or 1
    char_ratio = tgt_chars / src_chars
    hard = (not ALIGN_COUNT_HARD[0] <= count_ratio <= ALIGN_COUNT_HARD[1]
            or char_ratio < ALIGN_CHARS_HARD_LOW)
    soft = (not ALIGN_COUNT_OK[0] <= count_ratio <= ALIGN_COUNT_OK[1]
            or not ALIGN_CHARS_OK[0] <= char_ratio <= ALIGN_CHARS_OK[1])
    if hard:
        severity = "fail"
    elif soft:
        severity = "warn"
    else:
        severity = "ok"
    return [{"layer": "structural", "name": "alignment", "severity": severity,
             "detail": (f"{len(cues)} translated vs {len(source_cues)} source cues "
                        f"(count ratio {count_ratio:.2f}, text ratio {char_ratio:.2f})")}]


def pair_cues_by_time(cues: list[dict], source_cues: list[dict]) -> list[tuple[dict, dict]]:
    """Pair each (sampled) target cue with the source cue whose start time is
    nearest. Index-zipping mis-pairs the judge's inputs the moment counts
    differ; time is the only stable join key."""
    pairs: list[tuple[dict, dict]] = []
    for t in cues:
        src = min(source_cues, key=lambda s, ts=t["start"]: abs(s["start"] - ts))
        pairs.append((src, t))
    return pairs


def _norm_text(text: str) -> str:
    """Casefolded text with punctuation stripped, so punctuation drift
    ("that." vs "that") can't reset a repeat run."""
    return "".join(ch for ch in text.casefold() if ch.isalnum() or ch.isspace()).strip()


def _run_key(cue: dict) -> str | None:
    """Normalized repeat key for a cue; None for cues that never join runs
    (♪ musical refrains are legitimate repetition)."""
    if "♪" in cue["text"]:
        return None
    return _norm_text(cue["text"]) or None


def _longest_repeat_run(cues: list[dict]) -> dict | None:
    """The longest run of consecutive cues with identical NORMALIZED text as
    {text, start, end, count}, or None if there's no run of >= 2. ♪ cues and
    blank cues never join runs."""
    if not cues:
        return None
    best_len, best_end_i = 1, 0
    run = 1
    for i in range(1, len(cues)):
        key, prev = _run_key(cues[i]), _run_key(cues[i - 1])
        run = run + 1 if key is not None and key == prev else 1
        if run > best_len:
            best_len, best_end_i = run, i
    if best_len < 2:
        return None
    start_i = best_end_i - best_len + 1
    return {
        "text": cues[best_end_i]["text"],
        "start": cues[start_i]["start"],
        "end": cues[best_end_i]["end"],
        "count": best_len,
    }


def _longest_small_vocab_stretch(cues: list[dict]) -> int:
    """Length of the longest stretch of consecutive cues drawing on
    <= LOOP_DISTINCT_MAX distinct normalized texts. ♪/blank cues are excluded
    (they'd make songs look like loops). Classic two-pointer window."""
    keys = [k for k in (_run_key(c) for c in cues) if k is not None]
    best = 0
    counts: dict[str, int] = {}
    left = 0
    for right, key in enumerate(keys):
        counts[key] = counts.get(key, 0) + 1
        while len(counts) > LOOP_DISTINCT_MAX:
            lk = keys[left]
            counts[lk] -= 1
            if counts[lk] == 0:
                del counts[lk]
            left += 1
        best = max(best, right - left + 1)
    return best


def _repeat_severity(run: int, text: str = "") -> str:
    short = _repeat_word_count(text) <= SHORT_LINE_MAX_WORDS
    warn = SHORT_REPEAT_RUN_WARN if short else REPEAT_RUN_WARN
    fail = SHORT_REPEAT_RUN_FAIL if short else REPEAT_RUN_FAIL
    if run >= fail:
        return "fail"
    if run >= warn:
        return "warn"
    return "ok"


def _repeat_word_count(text: str) -> int:
    """Word count of a cue, ignoring leading dialogue dashes/bullets so a
    one-word answer like "— Jimsy." counts as 1 word, not 2 tokens."""
    stripped = text.strip().lstrip("—–-•♪>").strip()
    return len(stripped.split())


def _check_repeats(cues: list[dict]) -> list[dict]:
    repeated = _longest_repeat_run(cues)
    run = repeated["count"] if repeated else 1
    repeat_check = {"layer": "heuristic", "name": "repeat_loop",
                    "severity": _repeat_severity(run, repeated["text"] if repeated else ""),
                    "detail": f"longest identical-line run: {run}"}
    if repeated is not None:
        repeat_check["repeated"] = repeated

    stretch = _longest_small_vocab_stretch(cues)
    if stretch >= LOOP_FAIL_LEN:
        loop_sev = "fail"
    elif stretch >= LOOP_WARN_LEN:
        loop_sev = "warn"
    else:
        loop_sev = "ok"
    loop_check = {"layer": "heuristic", "name": "loop_vocabulary", "severity": loop_sev,
                  "detail": (f"{stretch} consecutive cues use <= {LOOP_DISTINCT_MAX} "
                             f"distinct lines" if loop_sev != "ok" else "")}
    return [repeat_check, loop_check]


def _check_artifacts(cues: list[dict]) -> dict:
    low = "\n".join(c["text"] for c in cues).lower()
    hits = [p for p in STRONG_ARTIFACT_PHRASES if p in low]

    if cues:
        span_start = min(c["start"] for c in cues)
        span_end = max(c["end"] for c in cues)
        for c in cues:
            norm = _norm_text(c["text"])
            if not norm:
                continue
            at_edge = (c["start"] - span_start <= WEAK_ARTIFACT_EDGE_SECONDS
                       or span_end - c["start"] <= WEAK_ARTIFACT_EDGE_SECONDS)
            if not at_edge:
                continue
            weak_chars = sum(len(_norm_text(p)) for p in WEAK_ARTIFACT_PHRASES
                             if _norm_text(p) in norm)
            if weak_chars / len(norm) >= WEAK_ARTIFACT_COVERAGE:
                hits.append(c["text"][:40])
    return {"layer": "heuristic", "name": "artifact_phrase",
            "severity": "warn" if hits else "ok",
            "detail": f"found: {hits[:5]}" if hits else ""}


def _check_blank_cues(cues: list[dict]) -> dict:
    blanks = sum(1 for c in cues if not c["text"].strip())
    frac = blanks / len(cues)
    if frac > BLANK_FAIL_FRACTION:
        sev = "fail"
    elif frac > BLANK_WARN_FRACTION:
        sev = "warn"
    else:
        sev = "ok"
    return {"layer": "heuristic", "name": "blank_cues", "severity": sev,
            "detail": f"{blanks}/{len(cues)} cues have no text" if blanks else ""}


def _check_gaps(cues: list[dict]) -> dict:
    # Informational only: long no-dialogue stretches are normal in film/TV
    # (action scenes, music), so gaps never drive the verdict — they're surfaced
    # for the user to glance at. The real "subtitles missing" signal is the
    # `coverage` structural check (truncation) + `repeat_loop` (dropouts).
    gaps = [round(b["start"] - a["end"], 1) for a, b in zip(cues, cues[1:])
            if b["start"] - a["end"] >= GAP_WARN_SECONDS]
    return {"layer": "heuristic", "name": "silence_gaps", "severity": "ok",
            "detail": f"{len(gaps)} gap(s) >= {GAP_WARN_SECONDS:.0f}s (max {max(gaps)}s)" if gaps else ""}


def _cue_cps(c: dict) -> float | None:
    dur = c["end"] - c["start"]
    flat = " ".join(c["text"].splitlines())
    return len(flat) / dur if dur > 0 else None


def _check_reading_speed(cues: list[dict]) -> dict:
    fast = [c["index"] for c in cues if (_cue_cps(c) or 0) > CPS_MAX]
    # Only a systemic share of rushed cues is a real signal — a few are an
    # unavoidable side effect of packing tight cue runs.
    too_many = len(fast) > CPS_WARN_FRACTION * len(cues)
    return {"layer": "heuristic", "name": "reading_speed",
            "severity": "warn" if too_many else "ok",
            "detail": f"{len(fast)}/{len(cues)} cues exceed {CPS_MAX} cps" if fast else ""}


def _check_line_length(cues: list[dict]) -> dict:
    lines = [ln for c in cues for ln in c["text"].splitlines() if ln.strip()]
    long_lines = sum(1 for ln in lines if len(ln) > LINE_LENGTH_LIMIT)
    too_many = lines and long_lines / len(lines) > LINE_LENGTH_WARN_FRACTION
    return {"layer": "heuristic", "name": "line_length",
            "severity": "warn" if too_many else "ok",
            "detail": (f"{long_lines}/{len(lines)} lines exceed "
                       f"{LINE_LENGTH_LIMIT} chars" if long_lines else "")}


def check_heuristics(cues: list[dict]) -> list[dict]:
    if not cues:
        return [{"layer": "heuristic", "name": "has_content", "severity": "fail",
                 "detail": "no cues to inspect"}]
    checks = _check_repeats(cues)
    checks.append(_check_artifacts(cues))
    checks.append(_check_blank_cues(cues))
    checks.append(_check_gaps(cues))
    checks.append(_check_reading_speed(cues))
    checks.append(_check_line_length(cues))
    return checks


def compute_metrics(cues: list[dict], video_duration: float | None) -> dict:
    """Per-job quality numbers for the report/UI scorecard. Descriptive only —
    they never drive the verdict."""
    cps_values = sorted(v for v in (_cue_cps(c) for c in cues if c["text"].strip())
                        if v is not None)

    def pct(p: float) -> float:
        if not cps_values:
            return 0.0
        return round(cps_values[min(len(cps_values) - 1, int(p * len(cps_values)))], 1)

    durations = [c["end"] - c["start"] for c in cues]
    gaps = [b["start"] - a["end"] for a, b in zip(cues, cues[1:])]
    coverage = (max((c["end"] for c in cues), default=0.0) / video_duration
                if video_duration and video_duration > 0 else None)
    return {
        "cue_count": len(cues),
        "coverage_ratio": round(coverage, 3) if coverage is not None else None,
        "cps_p50": pct(0.50),
        "cps_p95": pct(0.95),
        "cps_max": round(cps_values[-1], 1) if cps_values else 0.0,
        "pct_cues_over_20cps": round(
            100 * sum(1 for v in cps_values if v > 20) / len(cps_values), 1
        ) if cps_values else 0.0,
        "min_duration": round(min(durations), 3) if durations else 0.0,
        "gaps_over_90s": sum(1 for g in gaps if g >= GAP_WARN_SECONDS),
        "max_gap": round(max(gaps), 1) if gaps else 0.0,
    }


def sample_cues(cues: list[dict], k: int = SAMPLE_CUES) -> list[dict]:
    """Evenly-spaced sample preserving order (deterministic - no RNG)."""
    if len(cues) <= k:
        return list(cues)
    step = len(cues) / k
    return [cues[int(i * step)] for i in range(k)]


# Appended to every judge prompt to keep replies machine-parseable. Local
# models otherwise wrap JSON in markdown or add commentary (see the resilient
# parse_judge_response, which is the real safety net).
_JUDGE_FORMAT = (
    " Output ONLY the raw JSON object — no markdown fences, no commentary. "
    "Keep each issue under 12 words and use plain apostrophes, never double quotes, inside it."
)


def build_judge_prompt(cues: list[dict], source_cues: list[dict] | None) -> tuple[str, str]:
    if source_cues:
        system = (
            "You are a subtitle quality judge. Rate whether the TRANSLATED lines are a "
            "coherent, faithful translation of the SOURCE lines. Reply with JSON: "
            '{"score": 0-100, "verdict": "ok|bad", "issues": ["..."]}.' + _JUDGE_FORMAT
        )
        pairs = "\n".join(f"{i+1}. SRC: {s['text']!r}  TGT: {t['text']!r}"
                          for i, (s, t) in enumerate(zip(source_cues, cues)))
        user = f"Judge these source/target subtitle pairs:\n{pairs}"
    else:
        system = (
            "You are a subtitle quality judge. Rate whether these subtitle lines read as "
            "coherent, real human speech (not gibberish, repetition, or hallucinated text). "
            'Reply with JSON: {"score": 0-100, "verdict": "ok|bad", "issues": ["..."]}.' + _JUDGE_FORMAT
        )
        user = "Judge these subtitle lines:\n" + "\n".join(
            f"{i+1}. {c['text']!r}" for i, c in enumerate(cues))
    return system, user


def _severity_from_score(score) -> str | None:
    if not isinstance(score, (int, float)):
        return None
    if score >= 70:
        return "ok"
    if score >= 50:
        return "warn"
    return "fail"


def _semantic_check(severity: str, detail: str) -> dict:
    return {"layer": "semantic", "name": "llm_coherence", "severity": severity, "detail": detail}


def _json_candidates(text: str) -> list[str]:
    """Strings to try json.loads on, most-to-least likely: the whole cleaned
    reply, the greedy first{..}last brace span, then each flat brace object."""
    cands = [text]
    greedy = re.search(r"\{.*\}", text, re.DOTALL)
    if greedy:
        cands.append(greedy.group())
    cands.extend(re.findall(r"\{[^{}]*\}", text, re.DOTALL))
    return cands


def _verdict_from_dict(data: object) -> dict | None:
    """A semantic Check from a parsed object, or None if it has no usable score."""
    if not isinstance(data, dict) or "score" not in data:
        return None
    sev = _severity_from_score(data.get("score"))
    if sev is None:
        return None
    issues = data.get("issues") or []
    detail = f"judge score {data.get('score')}" + (f"; issues: {issues[:3]}" if issues else "")
    return _semantic_check(sev, detail)


def _verdict_from_json(text: str) -> dict | None:
    """First JSON candidate in `text` that parses into a usable verdict."""
    for cand in _json_candidates(text):
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, TypeError):
            continue
        verdict = _verdict_from_dict(data)
        if verdict is not None:
            return verdict
    return None


def _verdict_from_loose_score(text: str) -> dict | None:
    """Last resort: pull a bare score out of malformed output so the layer still
    scores rather than silently skipping."""
    m = re.search(r'"?score"?\s*[:=]\s*(\d{1,3})', text)
    if not m:
        return None
    sev = _severity_from_score(int(m.group(1)))
    return _semantic_check(sev, f"judge score {m.group(1)} (recovered)") if sev else None


def parse_judge_response(raw: str) -> dict:
    """Map the model's reply to a semantic Check — resiliently.

    Local models (gemma3) wrap JSON in ```fences```, append reasoning, or emit
    issue strings with unescaped quotes. Try several JSON candidates; if none
    parse, recover the score from the raw text so the coherence signal survives
    a slightly-malformed reply. Only genuinely unusable output -> 'skipped'."""
    cleaned = raw.replace("```json", "").replace("```", "").strip()
    return (
        _verdict_from_json(cleaned)
        or _verdict_from_loose_score(cleaned)
        or _semantic_check("skipped", "judge returned no parseable verdict")
    )


_SEVERITY_RANK = {"ok": 0, "skipped": 0, "warn": 1, "fail": 2}
_STATUS_BY_RANK = {0: "pass", 1: "warn", 2: "fail"}


def aggregate(checks: list[dict]) -> dict:
    worst = max((_SEVERITY_RANK[c["severity"]] for c in checks), default=0)
    status = _STATUS_BY_RANK[worst]
    fails = sum(1 for c in checks if c["severity"] == "fail")
    warns = sum(1 for c in checks if c["severity"] == "warn")
    score = max(0, 100 - fails * 40 - warns * 10)
    summary = f"{status.upper()} - {fails} fail, {warns} warn across {len(checks)} checks"
    return {"status": status, "score": float(score), "report": {"summary": summary, "checks": checks}}


def verify(
    srt_text: str,
    *,
    source_srt_text: str | None = None,
    video_duration: float | None = None,
    model_cfg: dict | None = None,
) -> dict:
    """Run all three layers and aggregate. model_cfg=None (or no LLM configured)
    => the semantic layer contributes one 'skipped' check. The LLM call is
    delegated to subtitle_verify_judge.judge_semantics (the only I/O)."""
    checks = check_structural(srt_text, video_duration)
    cues = parse_srt(srt_text)
    checks += check_heuristics(cues)

    source_cues = parse_srt(source_srt_text) if source_srt_text else None
    if source_cues:
        checks += check_alignment(cues, source_cues)

    if model_cfg:
        from app.worker.subtitle_verify_judge import judge_semantics
        checks.append(judge_semantics(cues, source_cues, model_cfg))
    else:
        checks.append({"layer": "semantic", "name": "llm_coherence", "severity": "skipped",
                       "detail": "no LLM configured on this profile"})
    result = aggregate(checks)
    result["report"]["metrics"] = compute_metrics(cues, video_duration)
    return result
