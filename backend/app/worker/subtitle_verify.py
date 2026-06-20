"""Pure subtitle-verification checks. No I/O, no worker imports.

Mirrors cue_timing.py: deterministic, table-testable helpers. The LLM judge
(the only I/O) lives in subtitle_verify_judge.py and is composed in by verify().
"""
from __future__ import annotations

import json
import re

MAX_CHARS_PER_LINE = 42
# >= N identical consecutive cues = hallucination loop. Tuned to 8 from real
# data: legit subtitles repeat short lines (sound cues, "No. No.") up to ~6 in a
# row; Whisper hallucination loops run far longer (10s-100s).
REPEAT_RUN_FAIL = 8
COVERAGE_MIN_RATIO = 0.5
MIN_CUES = 1
# Per-cue reading-speed ceiling. 35 (not the comfortable ~17) flags only
# genuinely rushed cues; a handful are unavoidable (enforce_timing packs tight
# runs), so reading_speed only warns when MORE than CPS_WARN_FRACTION of cues
# exceed it — i.e. a systemic problem, not the odd dense line. Real data: clean
# sources sit ~0%, dense translations ~3%, both below the 5% gate.
CPS_MAX = 35.0
CPS_WARN_FRACTION = 0.05
GAP_WARN_SECONDS = 90.0     # silent gaps shorter than this are normal (scene/music)
SAMPLE_CUES = 25
ARTIFACT_PHRASES = (
    "thanks for watching", "subtitles by", "amara.org",
    "subscribe", "www.", ".com/sub",
)

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

    # Overlaps are a soft signal, not "broken": enforce_timing deliberately
    # permits sub-second overlaps in tightly-packed cue runs to keep each cue on
    # screen for the minimum readable duration. So warn (don't fail) on them.
    overlaps = [b["index"] for a, b in zip(cues, cues[1:]) if b["start"] < a["end"]]
    checks.append({"layer": "structural", "name": "no_overlap",
                   "severity": "warn" if overlaps else "ok",
                   "detail": f"overlapping cues: {overlaps[:5]}" if overlaps else ""})

    if video_duration and video_duration > 0:
        ratio = cues[-1]["end"] / video_duration
        checks.append({"layer": "structural", "name": "coverage",
                       "severity": _coverage_severity(ratio),
                       "detail": f"subtitles cover {ratio*100:.0f}% of runtime"})
    return checks


def _max_repeat_run(cues: list[dict]) -> int:
    mx = run = 1 if cues else 0
    for i in range(1, len(cues)):
        run = run + 1 if cues[i]["text"] == cues[i - 1]["text"] else 1
        mx = max(mx, run)
    return mx


def check_heuristics(cues: list[dict]) -> list[dict]:
    checks: list[dict] = []
    if not cues:
        return [{"layer": "heuristic", "name": "has_content", "severity": "fail",
                 "detail": "no cues to inspect"}]

    run = _max_repeat_run(cues)
    checks.append({"layer": "heuristic", "name": "repeat_loop",
                   "severity": "fail" if run >= REPEAT_RUN_FAIL else "ok",
                   "detail": f"longest identical-line run: {run}"})

    low = "\n".join(c["text"] for c in cues).lower()
    hits = [p for p in ARTIFACT_PHRASES if p in low]
    checks.append({"layer": "heuristic", "name": "artifact_phrase",
                   "severity": "warn" if hits else "ok",
                   "detail": f"found: {hits}" if hits else ""})

    # Informational only: long no-dialogue stretches are normal in film/TV
    # (action scenes, music), so gaps never drive the verdict — they're surfaced
    # for the user to glance at. The real "subtitles missing" signal is the
    # `coverage` structural check (truncation) + `repeat_loop` (dropouts).
    gaps = [round(b["start"] - a["end"], 1) for a, b in zip(cues, cues[1:])
            if b["start"] - a["end"] >= GAP_WARN_SECONDS]
    checks.append({"layer": "heuristic", "name": "silence_gaps", "severity": "ok",
                   "detail": f"{len(gaps)} gap(s) >= {GAP_WARN_SECONDS:.0f}s (max {max(gaps)}s)" if gaps else ""})

    fast = []
    for c in cues:
        dur = c["end"] - c["start"]
        flat = " ".join(c["text"].splitlines())
        if dur > 0 and len(flat) / dur > CPS_MAX:
            fast.append(c["index"])
    # Only a systemic share of rushed cues is a real signal — a few are an
    # unavoidable side effect of packing tight cue runs.
    too_many = len(fast) > CPS_WARN_FRACTION * len(cues)
    checks.append({"layer": "heuristic", "name": "reading_speed",
                   "severity": "warn" if too_many else "ok",
                   "detail": f"{len(fast)}/{len(cues)} cues exceed {CPS_MAX} cps" if fast else ""})
    return checks


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

    if model_cfg:
        from app.worker.subtitle_verify_judge import judge_semantics
        source_cues = parse_srt(source_srt_text) if source_srt_text else None
        checks.append(judge_semantics(cues, source_cues, model_cfg))
    else:
        checks.append({"layer": "semantic", "name": "llm_coherence", "severity": "skipped",
                       "detail": "no LLM configured on this profile"})
    return aggregate(checks)
