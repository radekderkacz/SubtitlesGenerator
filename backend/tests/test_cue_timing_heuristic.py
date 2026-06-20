"""Heuristic (segment-only) path tests — the path that runs in production,
since the configured transcription server returns segment-level timestamps
only. See REVISION 2026-06-18 in the spec."""
from app.worker.cue_timing import (
    format_cues_from_segments,
    segments_to_sentence_cues,
)


def test_segment_splits_into_proportional_nonoverlapping_cues():
    segs = [{"start": 0.0, "end": 10.0, "text": "Hello there. How are you?"}]
    cues = segments_to_sentence_cues(segs)
    assert [c["text"] for c in cues] == ["Hello there.", "How are you?"]
    # spans the whole segment, contiguous and non-overlapping
    assert cues[0]["start"] == 0.0
    assert cues[-1]["end"] == 10.0
    for a, b in zip(cues, cues[1:]):
        assert abs(b["start"] - a["end"]) < 1e-9   # contiguous
        assert b["start"] >= a["start"]            # monotonic
    # equal-length sentences -> ~equal split near the midpoint
    assert abs(cues[0]["end"] - 5.0) < 0.5


def test_segment_without_sentence_punctuation_is_single_cue():
    segs = [{"start": 2.0, "end": 5.0, "text": "just a fragment no punctuation"}]
    cues = segments_to_sentence_cues(segs)
    assert len(cues) == 1
    assert cues[0]["start"] == 2.0 and cues[0]["end"] == 5.0
    assert cues[0]["text"] == "just a fragment no punctuation"


def test_empty_text_segment_skipped():
    segs = [{"start": 0.0, "end": 1.0, "text": "   "},
            {"start": 1.0, "end": 2.0, "text": "Real."}]
    cues = segments_to_sentence_cues(segs)
    assert [c["text"] for c in cues] == ["Real."]


def test_punctuation_only_segment_skipped():
    segs = [{"start": 0.0, "end": 1.0, "text": "..."},
            {"start": 1.0, "end": 2.0, "text": "Words here."}]
    cues = segments_to_sentence_cues(segs)
    assert [c["text"] for c in cues] == ["Words here."]


def test_proportional_distribution_favors_longer_sentence():
    # two sentences: a tiny one then a long one -> long one gets more time
    segs = [{"start": 0.0, "end": 12.0, "text": "Hi. " + "word " * 10 + "stop."}]
    cues = segments_to_sentence_cues(segs)
    assert len(cues) == 2
    assert (cues[1]["end"] - cues[1]["start"]) > (cues[0]["end"] - cues[0]["start"])


def test_multiple_segments_stay_globally_ordered():
    segs = [{"start": 0.0, "end": 4.0, "text": "First. Second."},
            {"start": 4.0, "end": 8.0, "text": "Third. Fourth."}]
    cues = segments_to_sentence_cues(segs)
    assert [c["text"] for c in cues] == ["First.", "Second.", "Third.", "Fourth."]
    starts = [c["start"] for c in cues]
    assert starts == sorted(starts)
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"] - 1e-9


def test_segments_to_sentence_cues_empty():
    assert segments_to_sentence_cues([]) == []


def test_format_cues_from_segments_applies_timing_and_wrapping():
    segs = [{"start": 0.0, "end": 30.0,
             "text": "This is a very long single sentence that certainly exceeds forty two chars on one line."}]
    cues = format_cues_from_segments(segs)
    for c in cues:
        assert all(len(ln) <= 42 for ln in c["text"].split("\n"))
        assert c["end"] <= c["start"] + 7.0 + 1e-9   # max duration enforced


def test_format_cues_from_segments_real_multi_sentence():
    # the all-at-once symptom: one segment, several sentences -> several timed cues
    segs = [{"start": 0.0, "end": 9.0,
             "text": "Look out! The bridge is closed. We have to turn back now."}]
    cues = format_cues_from_segments(segs)
    assert len(cues) == 3
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"] - 1e-9
