"""Heuristic (segment-only) path tests — the path that runs in production,
since the configured transcription server returns segment-level timestamps
only. See REVISION 2026-06-18 in the spec."""
from app.worker.cue_timing import (
    _split_sentences,
    split_long_cue_text,
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
    # (capitalized continuation, as real ASR output is; lowercase after a
    # period is deliberately NOT a sentence boundary since WS1)
    segs = [{"start": 0.0, "end": 12.0, "text": "Hi. " + "Word " * 10 + "stop."}]
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


# --- WS1: split_long_cue_text ----------------------------------------------------

def test_split_long_text_cue_by_clause():
    text = ("When the rain finally stopped falling on the valley, "
            "the villagers came out to inspect the damage together")
    out = split_long_cue_text({"text": text, "start": 0.0, "end": 6.0})
    assert len(out) == 2
    assert out[0]["text"].endswith(",")
    assert all(len(c["text"]) <= 84 for c in out)
    assert out[0]["end"] == out[1]["start"]
    assert abs(out[-1]["end"] - 6.0) < 1e-9


def test_split_short_cue_is_noop():
    cue = {"text": "Short line.", "start": 0.0, "end": 2.0}
    assert split_long_cue_text(cue) == [cue]


def test_split_unspaced_wall_is_bounded():
    cue = {"text": "x" * 300, "start": 0.0, "end": 10.0}
    out = split_long_cue_text(cue)
    assert all(len(c["text"]) <= 84 for c in out) and len(out) >= 4


# --- WS1: unified finalize chain --------------------------------------------------

def test_heuristic_dense_segment_is_split_and_two_lines_max():
    # Audit probe: 600 chars / 60s / no punctuation was ONE 7s 15-line cue
    seg = [{"start": 0.0, "end": 60.0, "text": ("word " * 120).strip()}]
    cues = format_cues_from_segments(seg)
    assert len(cues) >= 7
    assert all(len(c["text"].split("\n")) <= 2 for c in cues)
    assert all(c["end"] > c["start"] for c in cues)
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"] + 0.08 - 1e-9


def test_heuristic_zero_duration_segment_does_not_overlap():
    segs = [{"start": 5.0, "end": 5.0, "text": "One. Two. Three."},
            {"start": 6.0, "end": 9.0, "text": "Four."}]
    cues = format_cues_from_segments(segs)
    assert cues
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"] + 0.08 - 1e-9


def test_heuristic_overlapping_segments_produce_ordered_output():
    segs = [{"start": 0.0, "end": 6.0, "text": "Outer sentence one."},
            {"start": 2.0, "end": 4.0, "text": "Nested sentence."},
            {"start": 6.1, "end": 10.0, "text": "Tail sentence."}]
    cues = format_cues_from_segments(segs)
    starts = [c["start"] for c in cues]
    assert starts == sorted(starts)
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"] + 0.08 - 1e-9


# --- WS1: abbreviation/decimal/CJK-aware sentence splitting -----------------------

def test_abbreviations_do_not_split():
    assert _split_sentences("Dr. Smith arrived at 3.14 p.m. yesterday.") == \
        ["Dr. Smith arrived at 3.14 p.m. yesterday."]


def test_initialisms_do_not_split():
    assert _split_sentences("The U.S.A. is big.") == ["The U.S.A. is big."]


def test_normal_sentences_still_split():
    assert _split_sentences("It works. Try it! Really?") == ["It works.", "Try it!", "Really?"]


def test_cjk_terminators_split():
    assert _split_sentences("これは文です。二番目の文。") == ["これは文です。", "二番目の文。"]


def test_pure_punctuation_yields_nothing():
    assert _split_sentences("...") == []


def test_ellipsis_then_capital_splits():
    assert _split_sentences("Wait… Now go.") == ["Wait…", "Now go."]


def test_dense_84char_cue_never_exceeds_two_lines():
    # 84 chars fits MAX_CUE_CHARS but may have no word boundary allowing a
    # 2x42 wrap — the cue must then split in time, not grow a third line.
    segs = [{"start": 0.0, "end": 2.0,
             "text": "This is an extremely dense segment with far too many characters for its short span."}]
    cues = format_cues_from_segments(segs)
    assert all(len(c["text"].split("\n")) <= 2 for c in cues)
    assert all(all(len(ln) <= 42 for ln in c["text"].split("\n")) for c in cues)
