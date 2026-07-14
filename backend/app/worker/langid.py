"""Output language identification. Lazy, graceful, worker-only.

The classic silent translation failure is output in the WRONG language — the
model echoes the source or answers in English. fastText language ID is
microsecond-fast on CPU; the small model ships inside the fast-langdetect
wheel (low_memory mode), so no runtime download. Every failure degrades to
"no information" (None) — never blocks a job by itself.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Below these floors the classifier is guessing, not detecting.
MIN_TEXT_CHARS = 40
MIN_CONFIDENCE = 0.65

DetectFn = Callable[[str], Optional[tuple[str, float]]]

_detector: DetectFn | None = None
_detector_failed = False


def _load_detector() -> DetectFn | None:
    global _detector, _detector_failed
    if _detector is not None or _detector_failed:
        return _detector
    try:
        from fast_langdetect import detect

        def _fn(text: str) -> Optional[tuple[str, float]]:
            # model="lite" pins the small model bundled with the package —
            # the default resolution downloads the 125MB lid.176.bin at
            # runtime, which an offline worker must never do. The 1.x API
            # returns a ranked list of {lang, score} dicts.
            results = detect(text, model="lite", k=1)
            if not results:
                return None
            top = results[0]
            return (str(top["lang"]).lower(), float(top["score"]))

        _fn("hello world")  # force model load; failures surface here
        _detector = _fn
    # degrade to no-language-info
    except Exception as exc:  # noqa: BLE001
        logger.warning("language-ID unavailable (%s: %s)", type(exc).__name__, exc)
        _detector_failed = True
    return _detector


def detect_language(text: str, *, detect_fn: DetectFn | None = None) -> Optional[tuple[str, float]]:
    """(iso639-1, confidence) for the text, or None when undetectable
    (too short, low confidence, model unavailable)."""
    flat = " ".join(text.split())
    if len(flat) < MIN_TEXT_CHARS:
        return None
    fn = detect_fn or _load_detector()
    if fn is None:
        return None
    try:
        result = fn(flat)
    except Exception:  # noqa: BLE001
        return None
    if result is None:
        return None
    lang, score = result
    if score < MIN_CONFIDENCE:
        return None
    return lang, score


def batch_language_suspect(
    texts: list[str],
    target_language: str | None,
    source_language: str | None,
    *,
    detect_fn: DetectFn | None = None,
) -> bool:
    """True when a translated batch reads as the SOURCE language instead of
    the target — the strongest signal of an untranslated echo. Detection of
    any third language is left to verification (names/loanwords confuse
    per-batch checks)."""
    if not target_language or not source_language:
        return False
    tgt = target_language.strip().lower()
    src = source_language.strip().lower()
    if not tgt or not src or tgt == src:
        return False
    detected = detect_language(" ".join(texts), detect_fn=detect_fn)
    if detected is None:
        return False
    return detected[0] == src


def language_check(
    cues: list[dict],
    target_language: str | None,
    *,
    detect_fn: DetectFn | None = None,
) -> dict:
    """Verification check: the finished SRT's dominant language must match the
    job's target. Returns a heuristic-layer Check dict."""
    name = "output_language"
    if not target_language:
        return {"layer": "heuristic", "name": name, "severity": "ok",
                "detail": "no target language (source-only job)"}
    sample = " ".join(c.get("text", "") for c in cues[:200])
    detected = detect_language(sample, detect_fn=detect_fn)
    if detected is None:
        return {"layer": "heuristic", "name": name, "severity": "ok",
                "detail": "language check unavailable"}
    lang, score = detected
    if lang == target_language.strip().lower():
        return {"layer": "heuristic", "name": name, "severity": "ok",
                "detail": f"detected {lang} ({score:.2f})"}
    return {"layer": "heuristic", "name": name, "severity": "fail",
            "detail": f"subtitles read as '{lang}' ({score:.2f}), expected "
                      f"'{target_language}' — translation likely failed"}
