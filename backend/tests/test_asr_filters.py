"""ASR post-transcription quality filters (WS2, 2026-07 quality audit):
confidence-based segment drops, hallucination-loop collapse, artifact-phrase
removal, and language-code normalization."""
from app.worker.asr_filters import filter_segments, normalize_lang_code


def _seg(text, start, end, **extra):
    return {"text": text, "start": start, "end": end, **extra}


# --- normalize_lang_code -----------------------------------------------------------

def test_full_names_map_to_iso1():
    assert normalize_lang_code("english") == "en"
    assert normalize_lang_code("Polish") == "pl"
    assert normalize_lang_code("GERMAN") == "de"


def test_iso2_and_iso3_map_to_iso1():
    assert normalize_lang_code("eng") == "en"
    assert normalize_lang_code("pol") == "pl"
    assert normalize_lang_code("deu") == "de"


def test_iso1_passes_through():
    assert normalize_lang_code("en") == "en"
    assert normalize_lang_code("pl") == "pl"


def test_unknown_passes_through_lowercased():
    assert normalize_lang_code(" Klingon ") == "klingon"


def test_empty_and_none_are_safe():
    assert normalize_lang_code("") == ""
    assert normalize_lang_code(None) == ""


# --- filter_segments: confidence ---------------------------------------------------

def test_confident_speech_is_kept():
    segs = [_seg("Real dialogue.", 0, 2, no_speech_prob=0.05, avg_logprob=-0.3)]
    result = filter_segments(segs)
    assert result.segments == segs and result.dropped == []


def test_low_confidence_nonspeech_is_dropped():
    segs = [_seg("Real line.", 0, 2, no_speech_prob=0.05, avg_logprob=-0.3),
            _seg("ghost text", 2, 4, no_speech_prob=0.92, avg_logprob=-1.4)]
    result = filter_segments(segs)
    assert [s["text"] for s in result.segments] == ["Real line."]
    assert result.dropped[0]["reason"] == "low_confidence"


def test_missing_confidence_fields_never_drop():
    segs = [_seg("Line one.", 0, 2), _seg("Line two.", 2, 4)]
    result = filter_segments(segs)
    assert result.segments == segs


def test_high_no_speech_alone_is_not_dropped():
    # no_speech high but logprob fine — Whisper is often sure of quiet speech
    segs = [_seg("Whispered line.", 0, 2, no_speech_prob=0.8, avg_logprob=-0.2)]
    assert filter_segments(segs).segments == segs


# --- filter_segments: hallucination loop collapse ----------------------------------

def test_identical_run_collapses_to_two():
    segs = [_seg("Thank you.", i * 2.0, i * 2.0 + 1.5) for i in range(8)]
    result = filter_segments(segs)
    assert len(result.segments) == 2
    assert all(d["reason"] == "repeat_loop" for d in result.dropped)
    assert len(result.dropped) == 6


def test_run_of_two_is_untouched():
    segs = [_seg("No.", 0, 1), _seg("No.", 1.2, 2.2)]
    assert len(filter_segments(segs).segments) == 2


def test_near_identical_punctuation_drift_collapses():
    segs = ([_seg("I don't know that.", i * 2.0, i * 2.0 + 1.5) for i in range(3)]
            + [_seg("I don't know that", 6.0, 7.5)])
    result = filter_segments(segs)
    assert len(result.segments) == 2


def test_alternating_texts_are_not_collapsed():
    # A-B-A-B belongs to verification (needs semantic judgement), not generation
    segs = [_seg("Yes." if i % 2 == 0 else "No.", i * 2.0, i * 2.0 + 1.5) for i in range(10)]
    assert len(filter_segments(segs).segments) == 10


# --- filter_segments: artifact phrases ---------------------------------------------

def test_artifact_at_tail_is_dropped():
    segs = ([_seg("Real dialogue here.", i * 10.0, i * 10.0 + 5) for i in range(20)]
            + [_seg("Thanks for watching!", 200.0, 202.0)])
    result = filter_segments(segs)
    assert all("thanks" not in s["text"].lower() for s in result.segments)
    assert result.dropped[-1]["reason"] == "artifact_phrase"


def test_artifact_phrase_mid_film_is_kept():
    segs = ([_seg("Intro.", 0.0, 2.0)]
            + [_seg("Filler.", 10.0 + i, 11.0 + i) for i in range(300)]
            + [_seg("Thanks for watching!", 150.0, 152.0)]  # mid-span
            + [_seg("Outro.", 600.0, 602.0)])
    result = filter_segments(segs)
    assert any("Thanks for watching!" == s["text"] for s in result.segments)


def test_dialogue_containing_subscribe_is_kept():
    segs = [_seg("Real dialogue here.", 0.0, 2.0),
            _seg("I subscribe to that newspaper, always have.", 3.0, 6.0)]
    result = filter_segments(segs)
    assert len(result.segments) == 2


def test_subtitles_by_credit_at_start_is_dropped():
    segs = [_seg("Subtitles by the Amara.org community", 0.0, 3.0),
            _seg("Real dialogue.", 10.0, 12.0)]
    result = filter_segments(segs)
    assert [s["text"] for s in result.segments] == ["Real dialogue."]


# --- filter_segments: composition ---------------------------------------------------

def test_empty_input_is_empty_result():
    result = filter_segments([])
    assert result.segments == [] and result.dropped == []


def test_all_dropped_leaves_empty_list():
    segs = [_seg("Thanks for watching!", 0.0, 2.0)]
    result = filter_segments(segs)
    assert result.segments == [] and len(result.dropped) == 1


# --- filter_segments: VAD speech-region rejection (WS6) -----------------------------

def test_segment_outside_speech_regions_is_dropped():
    segs = [_seg("Real line.", 1.0, 3.0),
            _seg("Thanks hallucination.", 50.0, 52.0)]
    result = filter_segments(segs, speech_regions=[(0.5, 3.5)])
    assert [s["text"] for s in result.segments] == ["Real line."]
    assert result.dropped[0]["reason"] == "no_speech_region"


def test_segment_partially_overlapping_speech_is_kept():
    segs = [_seg("Trailing words linger.", 2.0, 6.0)]
    # 50% overlap with speech — keep (timing drift is normal)
    result = filter_segments(segs, speech_regions=[(0.0, 4.0)])
    assert result.segments == segs


def test_no_regions_info_disables_the_check():
    segs = [_seg("Line.", 100.0, 102.0)]
    assert filter_segments(segs, speech_regions=None).segments == segs


def test_empty_regions_drops_everything_speechless():
    segs = [_seg("Ghost.", 1.0, 2.0)]
    result = filter_segments(segs, speech_regions=[])
    assert result.segments == []
