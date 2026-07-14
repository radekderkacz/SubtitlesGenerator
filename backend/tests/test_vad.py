"""Speech-region detection (WS6, 2026-07 audit). Core region logic is tested
with an injected probability function; the real Silero model only runs in the
worker image (requirements/worker.txt), so model-dependent tests skip when
pysilero-vad isn't installed."""
import math
import struct
import wave

import pytest

from app.worker.vad import FRAME_SAMPLES, SAMPLE_RATE, detect_speech_regions


def _write_wav(path, seconds, *, tone=False):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        n = int(seconds * SAMPLE_RATE)
        if tone:
            frames = b"".join(
                struct.pack("<h", int(12000 * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE)))
                for i in range(n))
        else:
            frames = b"\x00\x00" * n
        w.writeframes(frames)


def _prob_from_schedule(schedule):
    """schedule: list of (start_s, end_s) that should read as speech."""
    state = {"i": 0}

    def prob(chunk: bytes) -> float:
        t = state["i"] * FRAME_SAMPLES / SAMPLE_RATE
        state["i"] += 1
        return 0.9 if any(s <= t < e for s, e in schedule) else 0.05
    return prob


def test_regions_merge_and_pad(tmp_path):
    wav = tmp_path / "a.wav"
    _write_wav(wav, 10.0)
    regions = detect_speech_regions(
        str(wav), prob_fn=_prob_from_schedule([(1.0, 3.0), (3.2, 5.0), (8.0, 9.0)]))
    # 1-3 and 3.2-5 merge across the 0.2s gap; 8-9 stays separate
    assert len(regions) == 2
    assert regions[0][0] <= 1.0 and regions[0][1] >= 5.0
    assert regions[1][0] <= 8.0 and regions[1][1] >= 9.0


def test_short_blips_are_dropped(tmp_path):
    wav = tmp_path / "b.wav"
    _write_wav(wav, 5.0)
    regions = detect_speech_regions(
        str(wav), prob_fn=_prob_from_schedule([(2.0, 2.1)]))  # 100ms blip
    assert regions == []


def test_all_silence_returns_empty(tmp_path):
    wav = tmp_path / "c.wav"
    _write_wav(wav, 3.0)
    regions = detect_speech_regions(str(wav), prob_fn=lambda chunk: 0.0)
    assert regions == []


def test_unreadable_file_returns_none(tmp_path):
    assert detect_speech_regions(str(tmp_path / "missing.wav"), prob_fn=lambda c: 0.0) is None


def test_real_model_scores_silence_as_no_speech(tmp_path):
    pytest.importorskip("pysilero_vad")
    wav = tmp_path / "silent.wav"
    _write_wav(wav, 3.0)
    regions = detect_speech_regions(str(wav))
    assert regions == []
