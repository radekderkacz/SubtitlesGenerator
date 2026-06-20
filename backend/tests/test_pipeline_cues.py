"""build_source_cues — the pipeline's source-of-cues chokepoint. Picks the
word path when the backend gives word timestamps, otherwise the segment-only
heuristic. See REVISION 2026-06-18 in the spec."""
from app.worker.tasks import build_source_cues


def test_build_source_cues_uses_words_when_present():
    result = {
        "language": "en",
        "segments": [{"start": 0.0, "end": 9.0, "text": "Hello there. How are you?"}],
        "words": [
            {"text": "Hello", "start": 0.0, "end": 0.4}, {"text": "there.", "start": 0.4, "end": 0.9},
            {"text": "How", "start": 1.0, "end": 1.3}, {"text": "are", "start": 1.3, "end": 1.5},
            {"text": "you?", "start": 1.5, "end": 2.0},
        ],
    }
    cues = build_source_cues(result)
    assert [c["text"] for c in cues] == ["Hello there.", "How are you?"]


def test_build_source_cues_heuristic_when_no_words():
    # REVISION: no words -> segment-only sentence-split heuristic (not 1 cue/segment)
    result = {"language": "en",
              "segments": [{"start": 0.0, "end": 9.0, "text": "Hello there. How are you?"}],
              "words": []}
    cues = build_source_cues(result)
    assert [c["text"] for c in cues] == ["Hello there.", "How are you?"]


def test_build_source_cues_accepts_bare_segment_list():
    # Defensive: a bare segment list (e.g. legacy callers / test doubles) is
    # treated as a no-words transcription and routed through the heuristic.
    cues = build_source_cues([{"start": 0.0, "end": 9.0, "text": "Hello there. How are you?"}])
    assert [c["text"] for c in cues] == ["Hello there.", "How are you?"]


def test_build_source_cues_single_sentence_segment_one_cue():
    result = {"segments": [{"start": 0.0, "end": 3.0, "text": "Just one line here"}], "words": []}
    cues = build_source_cues(result)
    assert len(cues) == 1
    assert cues[0]["text"] == "Just one line here"


def test_build_source_cues_empty():
    assert build_source_cues({"segments": [], "words": []}) == []
    assert build_source_cues([]) == []
