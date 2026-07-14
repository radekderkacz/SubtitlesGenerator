"""Voice-activity detection over the extracted 16 kHz mono WAV.

Whisper's worst public failure mode is hallucinating text over silence and
music ("Thanks for watching!", subtitle-credit loops). The transcription
backend is remote and can't be trusted to VAD-filter, so the worker detects
speech regions itself and the ASR filters reject segments that fall entirely
outside them. The regions are also persisted per job for the audio↔subtitle
sync self-check.

The Silero model (via pysilero-vad, which bundles the ONNX weights in the
wheel) is imported lazily and every failure degrades to "no VAD data" — the
pipeline never fails because of this module.
"""
from __future__ import annotations

import json
import logging
import os
import wave
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512               # Silero's native chunk at 16 kHz (32 ms)
SPEECH_THRESHOLD = 0.5
MIN_SPEECH_SECONDS = 0.25         # shorter bursts are clicks/noise
MERGE_GAP_SECONDS = 0.35          # bridge intra-sentence micro-pauses
PAD_SECONDS = 0.15                # keep word onsets/offsets inside regions

ProbFn = Callable[[bytes], float]


def _load_model_prob_fn() -> Optional[ProbFn]:
    try:
        from pysilero_vad import SileroVoiceActivityDetector

        detector = SileroVoiceActivityDetector()
        return detector  # callable: 16-bit mono PCM chunk -> probability
    # any model failure degrades to no-VAD
    except Exception as exc:  # noqa: BLE001
        logger.warning("Silero VAD unavailable (%s: %s) — skipping speech detection",
                       type(exc).__name__, exc)
        return None


def _frame_probabilities(wav_path: str, prob_fn: ProbFn) -> Optional[list[float]]:
    chunk_bytes = FRAME_SAMPLES * 2  # 16-bit mono
    probs: list[float] = []
    try:
        with wave.open(wav_path, "rb") as w:
            if w.getnchannels() != 1 or w.getframerate() != SAMPLE_RATE or w.getsampwidth() != 2:
                logger.warning("VAD skipped: %s is not 16kHz mono s16le", wav_path)
                return None
            while True:
                chunk = w.readframes(FRAME_SAMPLES)
                if len(chunk) < chunk_bytes:
                    break
                probs.append(float(prob_fn(chunk)))
    except (OSError, wave.Error) as exc:
        logger.warning("VAD skipped: cannot read %s (%s)", wav_path, exc)
        return None
    return probs


def _probs_to_regions(probs: list[float]) -> list[tuple[float, float]]:
    frame_s = FRAME_SAMPLES / SAMPLE_RATE
    raw: list[tuple[float, float]] = []
    start: float | None = None
    for i, p in enumerate(probs):
        t = i * frame_s
        if p >= SPEECH_THRESHOLD and start is None:
            start = t
        elif p < SPEECH_THRESHOLD and start is not None:
            raw.append((start, t))
            start = None
    if start is not None:
        raw.append((start, len(probs) * frame_s))

    merged: list[list[float]] = []
    for s, e in raw:
        if merged and s - merged[-1][1] <= MERGE_GAP_SECONDS:
            merged[-1][1] = e
        else:
            merged.append([s, e])
    return [
        (max(0.0, s - PAD_SECONDS), e + PAD_SECONDS)
        for s, e in merged
        if e - s >= MIN_SPEECH_SECONDS
    ]


def detect_speech_regions(
    wav_path: str, *, prob_fn: ProbFn | None = None
) -> Optional[list[tuple[float, float]]]:
    """Speech regions as (start_s, end_s) tuples, or None when VAD could not
    run (missing model, unreadable/incompatible audio) — None means "no
    information", while [] means "confidently no speech"."""
    fn = prob_fn or _load_model_prob_fn()
    if fn is None:
        return None
    probs = _frame_probabilities(wav_path, fn)
    if probs is None:
        return None
    return _probs_to_regions(probs)


def save_regions(path: str, regions: list[tuple[float, float]]) -> None:
    """Persist regions next to the job log (consumed by the sync self-check)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"sample_rate": SAMPLE_RATE, "regions": regions}, f)
    except OSError as exc:
        logger.warning("could not persist VAD regions to %s: %s", path, exc)


def load_regions(path: str) -> Optional[list[tuple[float, float]]]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [(float(s), float(e)) for s, e in data.get("regions", [])]
    except (OSError, ValueError, TypeError):
        return None


def vad_disabled() -> bool:
    """Kill switch for setups where client-side VAD misbehaves."""
    return os.environ.get("SUBGEN_DISABLE_VAD", "").lower() in ("1", "true", "yes")
