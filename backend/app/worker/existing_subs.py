"""Existing-subtitle discovery: sidecar files and embedded text tracks.

A video that ships with human-written subtitles beats ASR output every
time — IF the track is actually good. Discovery is deliberately
conservative: text-based tracks only (bitmap PGS/VobSub would need OCR),
forced tracks are skipped (they only cover foreign-language lines), and
every candidate must pass the verification gate in tasks.py (structural +
coverage + language ID + audio-sync) before it is used.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.worker.asr_filters import normalize_lang_code

# Codecs ffmpeg can convert to SRT without OCR.
_TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

# Sidecar naming flags that disqualify a file outright.
_FORCED_FLAGS = {"forced", "foreign"}
# Flags that are fine but aren't a language ("Movie.en.sdh.srt").
_NOISE_FLAGS = {"sdh", "hi", "cc", "full", "default"}


@dataclass
class SubCandidate:
    kind: str                    # "sidecar" | "embedded"
    path: str | None = None      # sidecar file path
    stream_index: int | None = None  # embedded: N in ffmpeg's s:N mapping
    language: str | None = None  # normalized iso639-1 tag, None = unknown

    def describe(self) -> str:
        if self.kind == "sidecar":
            return f"sidecar {os.path.basename(self.path or '?')}"
        return f"embedded track s:{self.stream_index} ({self.language or 'unknown'})"


def _sidecar_language(video_stem: str, srt_path: Path) -> str | None | bool:
    """Language tag between the video stem and .srt, normalized.

    Returns False when the file is disqualified (forced/foreign flag),
    None when no language tag is present ("Movie.srt")."""
    middle = srt_path.name[len(video_stem):-len(".srt")].strip(".")
    if not middle:
        return None
    flags = {p.lower() for p in middle.split(".")}
    if flags & _FORCED_FLAGS:
        return False
    langs = [normalize_lang_code(f) for f in flags if f not in _NOISE_FLAGS]
    langs = [lang for lang in langs if lang]
    return langs[0] if langs else None


def find_sidecar_candidates(video_path: str, exclude_paths: set[str]) -> list[SubCandidate]:
    """SRT files next to the video sharing its stem. ``exclude_paths`` keeps
    the job's own target output from being read as an input."""
    video = Path(video_path)
    out: list[SubCandidate] = []
    try:
        entries = sorted(video.parent.iterdir())
    except OSError:
        return out
    for p in entries:
        if not (p.is_file() and p.name.startswith(video.stem) and p.suffix.lower() == ".srt"):
            continue
        if str(p) in exclude_paths:
            continue
        lang = _sidecar_language(video.stem, p)
        if lang is False:
            continue
        out.append(SubCandidate(kind="sidecar", path=str(p), language=lang))
    return out


def probe_embedded_candidates(video_path: str) -> list[SubCandidate]:
    """Text-based, non-forced subtitle streams in the container. Best-effort:
    probe/import failures mean "no embedded candidates", never a crash."""
    try:
        import ffmpeg
        streams = ffmpeg.probe(video_path).get("streams", [])
    except Exception:
        return []
    out: list[SubCandidate] = []
    sub_index = -1
    for s in streams:
        if s.get("codec_type") != "subtitle":
            continue
        sub_index += 1
        if s.get("codec_name") not in _TEXT_SUB_CODECS:
            continue
        disposition = s.get("disposition") or {}
        if disposition.get("forced"):
            continue
        tag = (s.get("tags") or {}).get("language")
        out.append(SubCandidate(kind="embedded", stream_index=sub_index,
                                language=normalize_lang_code(tag) or None))
    return out


def extract_embedded(video_path: str, stream_index: int, out_path: str) -> bool:
    """Extract one embedded subtitle stream to an SRT file. False on failure."""
    try:
        import ffmpeg
        (ffmpeg
         .input(video_path)
         .output(out_path, map=f"0:s:{stream_index}", scodec="srt")
         .overwrite_output()
         .run(capture_stdout=True, capture_stderr=True))
    except Exception:
        return False
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def rank_candidates(
    candidates: list[SubCandidate], source_hint: str | None, target_language: str | None
) -> list[SubCandidate]:
    """Best-first: source-language match, then target-language (translation
    becomes a no-op), then known-language, sidecars before embedded (no
    extraction cost, usually purpose-downloaded)."""
    src = normalize_lang_code(source_hint) or None
    tgt = normalize_lang_code(target_language) or None

    def key(c: SubCandidate):
        return (
            0 if (src and c.language == src) else 1,
            0 if (tgt and c.language == tgt) else 1,
            0 if c.language else 1,
            0 if c.kind == "sidecar" else 1,
        )
    return sorted(candidates, key=key)


# SDH markup: bracketed sound cues, music lines, leading speaker labels.
_BRACKETED = re.compile(r"[\[(][^\])]*[\])]")
_SPEAKER_LABEL = re.compile(r"^[A-Z][A-Z0-9 .'-]{0,24}:\s*")
_MUSIC_LINE = re.compile(r"^[♪♫\s]*$|^[♪♫].*[♪♫]$")


def strip_sdh(cues: list[dict]) -> list[dict]:
    """Remove SDH markup a translation source shouldn't carry: [door slams],
    (SIGHS), ♪ lyrics lines ♪, and JOHN: speaker labels. Cues left empty
    are dropped entirely."""
    out: list[dict] = []
    for cue in cues:
        lines: list[str] = []
        for line in cue.get("text", "").splitlines():
            line = _BRACKETED.sub("", line)
            if _MUSIC_LINE.match(line.strip()):
                continue
            line = _SPEAKER_LABEL.sub("", line.strip()).strip()
            if line:
                lines.append(line)
        if lines:
            out.append({**cue, "text": "\n".join(lines)})
    return out
