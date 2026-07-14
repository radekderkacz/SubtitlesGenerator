"""Post-transcription ASR quality filters. Pure functions, no I/O.

Whisper-family models hallucinate on silence and music: looping segments,
credit-reel artifacts ("Thanks for watching!", "Subtitles by ..."), and
low-confidence ghost text. The transcription response carries the evidence
(``no_speech_prob``, ``avg_logprob``, ``compression_ratio``) — these filters
apply it at generation time so hallucinations never reach the SRT, instead of
only warning about them in post-hoc verification.

All rules degrade gracefully: confidence-based drops apply only when the
backend sends the fields; text/position rules always apply.
"""
from __future__ import annotations

from typing import NamedTuple

# Community-established Whisper filtering thresholds (see whisper#679 et al.).
NO_SPEECH_DROP = 0.6        # ...combined with low avg_logprob
AVG_LOGPROB_DROP = -1.0
COMPRESSION_RATIO_FLAG = 2.4
REPEAT_RUN_KEEP = 2         # identical-run segments kept; the rest drop
REPEAT_RUN_MIN = 3          # runs shorter than this are untouched
EDGE_WINDOW_SECONDS = 60.0  # credits-hallucination habitat at span edges

# Credit-reel phrases that are near-certain hallucinations at the edges of a
# transcript. Cross-reference: subtitle_verify.ARTIFACT_PHRASES warns about
# these post-hoc; the split into strong/weak here exists because generation-time
# DROPS need higher precision than verification-time WARNS.
STRONG_ARTIFACTS = (
    "thanks for watching",
    "thank you for watching",
    "subtitles by",
    "subtitled by",
    "captioned by",
    "captioning sponsored",
    "amara.org",
    "opensubtitles",
)
# Phrases that appear in legitimate dialogue; they only drop a segment that is
# essentially nothing but the phrase.
WEAK_ARTIFACTS = ("subscribe", "www.", ".com")
WEAK_COVERAGE = 0.6
# A segment must overlap detected speech by at least this fraction of its own
# duration to survive when VAD regions are available. Low on purpose: segment
# timing drifts, VAD padding is tight — only segments with essentially NO
# speech under them (the hallucination habitat) should drop.
SPEECH_OVERLAP_MIN = 0.2

# Whisper's verbose_json `language` is a full English name on hosted backends
# ("english") and an ISO-639-1 code on faster-whisper ("en"); users may type
# either or an ISO-639-2/3 code. Everything funnels to ISO-639-1 so SRT
# suffixes are player-recognizable (Movie.en.srt) and overlay lookups hit.
_LANG_TO_ISO1 = {
    "english": "en", "eng": "en",
    "polish": "pl", "pol": "pl",
    "german": "de", "deu": "de", "ger": "de",
    "spanish": "es", "spa": "es",
    "french": "fr", "fra": "fr", "fre": "fr",
    "italian": "it", "ita": "it",
    "portuguese": "pt", "por": "pt",
    "russian": "ru", "rus": "ru",
    "japanese": "ja", "jpn": "ja",
    "chinese": "zh", "zho": "zh", "chi": "zh", "mandarin": "zh",
    "korean": "ko", "kor": "ko",
    "dutch": "nl", "nld": "nl", "dut": "nl",
    "czech": "cs", "ces": "cs", "cze": "cs",
    "ukrainian": "uk", "ukr": "uk",
    "arabic": "ar", "ara": "ar",
    "hindi": "hi", "hin": "hi",
    "turkish": "tr", "tur": "tr",
    "swedish": "sv", "swe": "sv",
    "norwegian": "no", "nor": "no",
    "danish": "da", "dan": "da",
    "finnish": "fi", "fin": "fi",
    "greek": "el", "ell": "el", "gre": "el",
    "hungarian": "hu", "hun": "hu",
    "romanian": "ro", "ron": "ro", "rum": "ro",
    "vietnamese": "vi", "vie": "vi",
    "thai": "th", "tha": "th",
    "hebrew": "he", "heb": "he",
    "indonesian": "id", "ind": "id",
    "slovak": "sk", "slk": "sk", "slo": "sk",
    "bulgarian": "bg", "bul": "bg",
    "croatian": "hr", "hrv": "hr",
    "serbian": "sr", "srp": "sr",
    "catalan": "ca", "cat": "ca",
}


class FilterResult(NamedTuple):
    segments: list[dict]
    dropped: list[dict]


def normalize_lang_code(value: str | None) -> str:
    """Map a language name/code to ISO-639-1. Unknown values pass through
    lowercased and trimmed; never raises."""
    cleaned = (value or "").strip().lower()
    return _LANG_TO_ISO1.get(cleaned, cleaned)


def _norm(text: str) -> str:
    """Casefolded text with punctuation stripped, for loop/artifact matching."""
    return "".join(ch for ch in text.casefold() if ch.isalnum() or ch.isspace()).strip()


def _drop_entry(seg: dict, reason: str) -> dict:
    return {"reason": reason, "text": seg.get("text", ""),
            "start": seg.get("start"), "end": seg.get("end")}


def _is_low_confidence(seg: dict) -> bool:
    nsp, alp = seg.get("no_speech_prob"), seg.get("avg_logprob")
    return (nsp is not None and alp is not None
            and nsp > NO_SPEECH_DROP and alp < AVG_LOGPROB_DROP)


def _collapse_repeat_runs(segments: list[dict], dropped: list[dict]) -> list[dict]:
    """Keep the first REPEAT_RUN_KEEP of any run of >= REPEAT_RUN_MIN
    consecutive segments with identical normalized text (Whisper's looping
    failure mode). Alternating A-B-A-B patterns are left for verification."""
    out: list[dict] = []
    i = 0
    while i < len(segments):
        j = i
        key = _norm(segments[i].get("text", ""))
        while j < len(segments) and _norm(segments[j].get("text", "")) == key:
            j += 1
        run = segments[i:j]
        if key and len(run) >= REPEAT_RUN_MIN:
            out.extend(run[:REPEAT_RUN_KEEP])
            dropped.extend(_drop_entry(s, "repeat_loop") for s in run[REPEAT_RUN_KEEP:])
        else:
            out.extend(run)
        i = j
    return out


def _is_artifact(seg: dict, span_start: float, span_end: float) -> bool:
    norm = _norm(seg.get("text", ""))
    if not norm:
        return False
    start = seg.get("start") or 0.0
    at_edge = (start - span_start <= EDGE_WINDOW_SECONDS
               or span_end - start <= EDGE_WINDOW_SECONDS)
    suspicious = at_edge or (seg.get("no_speech_prob") or 0.0) > 0.5
    if not suspicious:
        return False
    if any(p in norm for p in (_norm(a) for a in STRONG_ARTIFACTS)):
        return True
    weak_hit = sum(len(_norm(p)) for p in WEAK_ARTIFACTS if _norm(p) in norm)
    return weak_hit / len(norm) >= WEAK_COVERAGE


def _speech_overlap_fraction(seg: dict, regions: list[tuple[float, float]]) -> float:
    start, end = seg.get("start") or 0.0, seg.get("end") or 0.0
    dur = end - start
    if dur <= 0:
        return 1.0  # zero-length garbage is the timing layer's problem
    covered = sum(max(0.0, min(end, r_end) - max(start, r_start))
                  for r_start, r_end in regions)
    return covered / dur


def filter_segments(
    segments: list[dict],
    *,
    speech_regions: list[tuple[float, float]] | None = None,
) -> FilterResult:
    """Apply VAD speech-region rejection (when regions are available),
    confidence drops, hallucination-loop collapse, and artifact-phrase
    removal, in that order. Returns the surviving segments plus a drop log
    (reason/text/start per dropped segment) for the job log.

    ``speech_regions=None`` means "no VAD information" (check disabled);
    ``[]`` means "confidently no speech anywhere"."""
    if not segments:
        return FilterResult([], [])
    dropped: list[dict] = []

    kept = []
    for seg in segments:
        if (speech_regions is not None
                and _speech_overlap_fraction(seg, speech_regions) < SPEECH_OVERLAP_MIN):
            dropped.append(_drop_entry(seg, "no_speech_region"))
        elif _is_low_confidence(seg):
            dropped.append(_drop_entry(seg, "low_confidence"))
        else:
            kept.append(seg)

    kept = _collapse_repeat_runs(kept, dropped)

    starts = [s.get("start") or 0.0 for s in segments]
    ends = [s.get("end") or 0.0 for s in segments]
    span_start, span_end = min(starts), max(ends)
    survivors = []
    for seg in kept:
        if _is_artifact(seg, span_start, span_end):
            dropped.append(_drop_entry(seg, "artifact_phrase"))
        else:
            survivors.append(seg)

    return FilterResult(survivors, dropped)
