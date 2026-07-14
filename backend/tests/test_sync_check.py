"""Audio↔subtitle sync self-check (WS13, 2026-07 audit)."""
import pytest

pytest.importorskip("numpy")

from app.worker.sync_check import subtitle_speech_offset, sync_check


def _cues_from(intervals):
    return [{"start": s, "end": e, "text": "x"} for s, e in intervals]


def _speech_pattern(shift=0.0, n=40):
    # speech bursts every 7s, 2s long — enough structure for a sharp peak
    return [(7.0 * i + shift, 7.0 * i + shift + 2.0) for i in range(n)]


def test_aligned_subtitles_measure_zero_offset():
    regions = _speech_pattern()
    offset = subtitle_speech_offset(_cues_from(regions), regions)
    assert offset is not None and abs(offset) < 0.2


def test_late_subtitles_measure_positive_offset():
    regions = _speech_pattern()
    cues = _cues_from(_speech_pattern(shift=3.0))  # subs 3s late
    offset = subtitle_speech_offset(cues, regions)
    assert offset is not None and 2.5 < offset < 3.5


def test_early_subtitles_measure_negative_offset():
    regions = _speech_pattern(shift=4.0)
    cues = _cues_from(_speech_pattern())          # subs 4s early
    offset = subtitle_speech_offset(cues, regions)
    assert offset is not None and -4.5 < offset < -3.5


def test_degenerate_inputs_are_none():
    assert subtitle_speech_offset([], [(0, 10)]) is None
    assert subtitle_speech_offset(_cues_from([(0, 1)]), []) is None
    assert subtitle_speech_offset(_cues_from([(0, 1)]), [(0, 1)]) is None  # too short


def test_sync_check_severities():
    regions = _speech_pattern()
    assert sync_check(_cues_from(regions), regions)["severity"] == "ok"
    late3 = _cues_from(_speech_pattern(shift=3.0))
    assert sync_check(late3, regions)["severity"] == "warn"
    late10 = _cues_from(_speech_pattern(shift=10.0))
    assert sync_check(late10, regions)["severity"] == "fail"
    assert sync_check(_cues_from(regions), None)["severity"] == "ok"
