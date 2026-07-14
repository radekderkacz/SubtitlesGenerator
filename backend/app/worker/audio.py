"""Audio-stream selection for extraction. Pure functions over ffprobe data.

ffmpeg's default stream selection picks the audio stream with the MOST
channels — on a typical MKV that means a 5.1 commentary track or a foreign
dub wins over the stereo original, and the whole subtitle file comes out
wrong. Selection order here: user's source-language hint, then the
container's default disposition, then the first audio stream.
"""
from __future__ import annotations

import os

from app.worker.asr_filters import _LANG_TO_ISO1

# iso1 -> every tag spelling that matches it in container metadata
# (ffprobe language tags are usually ISO-639-2: "eng", "pol", "fre"...).
_ISO1_TO_TAGS: dict[str, set[str]] = {}
for _tag, _iso1 in _LANG_TO_ISO1.items():
    _ISO1_TO_TAGS.setdefault(_iso1, {_iso1}).add(_tag)


def _hint_tags(language_hint: str | None) -> set[str]:
    if not language_hint:
        return set()
    iso1 = _LANG_TO_ISO1.get(language_hint.strip().lower(), language_hint.strip().lower())
    return _ISO1_TO_TAGS.get(iso1, {iso1})


def pick_audio_stream(probe: dict, language_hint: str | None) -> tuple[dict | None, int | None]:
    """(stream, relative_audio_index) of the dialogue track to extract, or
    (None, None) when the container has no audio streams. The relative index
    is what ffmpeg's ``a:N`` specifier wants."""
    audio = [s for s in probe.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio:
        return None, None
    tags = _hint_tags(language_hint)
    if tags:
        for rel, s in enumerate(audio):
            lang = ((s.get("tags") or {}).get("language") or "").lower()
            if lang in tags:
                return s, rel
    for rel, s in enumerate(audio):
        if (s.get("disposition") or {}).get("default"):
            return s, rel
    return audio[0], 0


def audio_filter_for(stream: dict | None) -> str | None:
    """Center-channel extraction filter for surround sources — dialogue lives
    in FC on standard layouts, so isolating it drops music/effects noise.
    Opt-in (SUBGEN_CENTER_CHANNEL=1): a nonstandard mix without a real FC
    would otherwise yield near-silence and a false 'no speech detected'."""
    if os.environ.get("SUBGEN_CENTER_CHANNEL", "").lower() not in ("1", "true", "yes"):
        return None
    if stream is None:
        return None
    channels = int(stream.get("channels") or 0)
    layout = (stream.get("channel_layout") or "").lower()
    if channels >= 5 or "5.1" in layout or "7.1" in layout:
        return "pan=mono|c0=FC"
    return None
