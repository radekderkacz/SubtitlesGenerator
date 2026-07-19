"""Second-pass gap recovery: gap finding, timeline offset, merge, worker hook."""
import asyncio
from unittest.mock import MagicMock

from app.worker import tasks
from app.worker.second_pass import (
    find_speech_gaps,
    merge_recovered,
    offset_segments,
)


# ---------------------------------------------------------------------------
# find_speech_gaps
# ---------------------------------------------------------------------------

def _seg(start, end, text="x"):
    return {"start": start, "end": end, "text": text}


def test_uncovered_region_is_a_gap():
    # Speech at 10-20s, no segments at all → the whole region is a gap.
    assert find_speech_gaps([(10.0, 20.0)], []) == [(10.0, 20.0)]


def test_fully_covered_region_yields_nothing():
    assert find_speech_gaps([(10.0, 20.0)], [_seg(9.0, 21.0)]) == []


def test_partial_coverage_yields_remainders():
    # Segment covers 12-15 inside a 10-20 region → gaps 10-12 and 15-20.
    gaps = find_speech_gaps([(10.0, 20.0)], [_seg(12.0, 15.0)])
    assert gaps == [(10.0, 12.0), (15.0, 20.0)]


def test_short_remainders_are_ignored():
    # 1s leftover < 2s minimum.
    assert find_speech_gaps([(10.0, 11.0)], []) == []


def test_gap_cap_keeps_longest():
    regions = [(float(i * 100), float(i * 100 + 2 + i)) for i in range(12)]
    gaps = find_speech_gaps(regions, [], max_gaps=8)
    assert len(gaps) == 8
    # The four shortest regions (2-5s) were dropped; the longest survive.
    assert min(b - a for a, b in gaps) > 5.0
    assert gaps == sorted(gaps)  # chronological output


def test_no_vad_regions_means_no_gaps():
    assert find_speech_gaps(None, [_seg(0, 1)]) == []
    assert find_speech_gaps([], []) == []


# ---------------------------------------------------------------------------
# offset + merge
# ---------------------------------------------------------------------------

def test_offset_segments_shifts_to_file_timeline():
    out = offset_segments([{"start": 0.5, "end": 2.0, "text": "hi"}], 100.0)
    assert out == [{"start": 100.5, "end": 102.0, "text": "hi"}]


def test_merge_keeps_chronological_order_and_drops_overlaps():
    segments = [_seg(0.0, 5.0, "a"), _seg(20.0, 25.0, "c")]
    recovered = [
        _seg(10.0, 12.0, "b"),          # fresh — kept
        _seg(21.0, 22.0, "dup"),        # midpoint inside existing 20-25 — dropped
        _seg(30.0, 31.0, "   "),        # blank text — dropped
    ]
    merged = merge_recovered(segments, recovered)
    assert [s["text"] for s in merged] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Worker hook
# ---------------------------------------------------------------------------

def _job(**kw):
    base = dict(id="j1", backend_profile={
        "transcription_api_url": "http://asr.test/v1",
        "transcription_model": "large-v3",
        "transcription_api_key": None,
    })
    base.update(kw)
    return type("J", (), base)()


def _transcription(segments):
    return {"language": "en", "segments": segments}


def test_second_pass_disabled_by_env(monkeypatch):
    monkeypatch.setenv("SUBGEN_DISABLE_SECOND_PASS", "1")
    t = _transcription([])
    out = asyncio.run(tasks._second_pass_recover(
        _job(), "j1", "/tmp/x.wav", "log", t, [(0.0, 30.0)]))
    assert out is t


def test_second_pass_noop_without_gaps(monkeypatch):
    monkeypatch.delenv("SUBGEN_DISABLE_SECOND_PASS", raising=False)
    t = _transcription([_seg(0.0, 30.0)])
    out = asyncio.run(tasks._second_pass_recover(
        _job(), "j1", "/tmp/x.wav", "log", t, [(0.0, 30.0)]))
    assert out is t


def test_second_pass_merges_recovered_segments(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBGEN_DISABLE_SECOND_PASS", raising=False)
    monkeypatch.setattr(tasks, "_write_log", MagicMock())
    monkeypatch.setattr(
        tasks, "_recover_gap_blocking",
        lambda audio, gap, url, model, key, lang: [
            {"start": gap[0] + 0.2, "end": gap[1] - 0.2, "text": "recovered line"}])
    t = _transcription([_seg(0.0, 10.0, "loud scene")])
    out = asyncio.run(tasks._second_pass_recover(
        _job(), "j1", "/tmp/x.wav", "log", t, [(0.0, 10.0), (50.0, 60.0)]))
    assert [s["text"] for s in out["segments"]] == ["loud scene", "recovered line"]
    assert out["segments"][1]["start"] == 50.2


def test_second_pass_failure_is_contained(monkeypatch):
    monkeypatch.delenv("SUBGEN_DISABLE_SECOND_PASS", raising=False)
    monkeypatch.setattr(tasks, "_write_log", MagicMock())

    def boom(*a, **kw):
        raise RuntimeError("asr down")
    monkeypatch.setattr(tasks, "_recover_gap_blocking", boom)
    t = _transcription([_seg(0.0, 10.0)])
    out = asyncio.run(tasks._second_pass_recover(
        _job(), "j1", "/tmp/x.wav", "log", t, [(50.0, 60.0)]))
    assert out is t  # untouched first-pass result


def test_second_pass_passes_through_legacy_bare_list(monkeypatch):
    monkeypatch.delenv("SUBGEN_DISABLE_SECOND_PASS", raising=False)
    legacy = [_seg(0.0, 1.0)]
    out = asyncio.run(tasks._second_pass_recover(
        _job(), "j1", "/tmp/x.wav", "log", legacy, [(50.0, 60.0)]))
    assert out is legacy
