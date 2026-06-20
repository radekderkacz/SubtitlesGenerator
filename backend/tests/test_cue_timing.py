from app.worker.cue_timing import (
    enforce_timing,
    format_cues,
    reflow_translated,
    split_long_sentence,
    words_to_cues,
    wrap_lines,
)


def _w(text, start, end):
    return {"text": text, "start": start, "end": end}


def test_splits_at_sentence_boundaries():
    words = [_w("Hello", 0.0, 0.4), _w("there.", 0.4, 0.9),
             _w("How", 1.0, 1.3), _w("are", 1.3, 1.5), _w("you?", 1.5, 2.0)]
    cues = words_to_cues(words)
    assert [c["text"] for c in cues] == ["Hello there.", "How are you?"]
    assert cues[0]["start"] == 0.0 and cues[0]["end"] == 0.9
    assert cues[1]["start"] == 1.0 and cues[1]["end"] == 2.0


def test_long_pause_forces_split_even_without_punctuation():
    words = [_w("wait", 0.0, 0.3), _w("for", 0.3, 0.5),
             _w("it", 3.0, 3.2), _w("now", 3.2, 3.5)]  # 2.5s gap
    cues = words_to_cues(words)
    assert [c["text"] for c in cues] == ["wait for", "it now"]


def test_empty_input_returns_empty():
    assert words_to_cues([]) == []


def test_single_word_one_cue():
    assert words_to_cues([_w("Go.", 0.0, 0.5)]) == [{"text": "Go.", "start": 0.0, "end": 0.5}]


def test_char_cap_forces_split_within_a_run():
    long = [_w("word", i * 0.3, i * 0.3 + 0.2) for i in range(40)]  # no punctuation, ~200 chars
    cues = words_to_cues(long)
    assert len(cues) >= 2
    assert all(len(c["text"]) <= 84 for c in cues)


def test_linger_extends_short_cue_into_silence():
    # 30 chars at 17 cps needs ~1.76s; speech is only 0.5s, next cue far away
    cues = [{"text": "x" * 30, "start": 0.0, "end": 0.5},
            {"text": "y", "start": 10.0, "end": 10.2}]
    out = enforce_timing(cues)
    assert abs(out[0]["end"] - (0.0 + 30 / 17.0)) < 0.01


def test_linger_never_crosses_into_next_cue():
    cues = [{"text": "x" * 30, "start": 0.0, "end": 0.5},
            {"text": "y", "start": 1.0, "end": 1.2}]
    out = enforce_timing(cues)
    assert out[0]["end"] <= 1.0 - 0.08 + 1e-9


def test_min_and_max_duration_enforced():
    cues = [{"text": "hi", "start": 0.0, "end": 0.1}]            # too short
    assert enforce_timing(cues)[0]["end"] == 1.0
    big = [{"text": "z" * 200, "start": 0.0, "end": 30.0}]        # too long
    assert enforce_timing(big)[0]["end"] == 7.0


def test_end_never_inverts_when_next_starts_immediately():
    cues = [{"text": "a" * 50, "start": 0.0, "end": 0.4},
            {"text": "b", "start": 0.45, "end": 0.6}]
    out = enforce_timing(cues)
    assert out[0]["end"] > out[0]["start"]


def test_short_text_single_line():
    assert wrap_lines("Hello there.") == "Hello there."


def test_wraps_into_two_balanced_lines():
    text = "The quick brown fox jumps over the lazy dog today"
    wrapped = wrap_lines(text)
    lines = wrapped.split("\n")
    assert len(lines) == 2
    assert all(len(ln) <= 42 for ln in lines)
    assert wrapped.replace("\n", " ") == text


def test_never_breaks_mid_word():
    wrapped = wrap_lines("antidisestablishmentarianism supercalifragilistic")
    for ln in wrapped.split("\n"):
        assert " " in ln or ln in ("antidisestablishmentarianism", "supercalifragilistic")


def test_split_long_sentence_breaks_at_clause():
    # one ~10s sentence with a comma; should split into >=2 sub-cues under caps
    words = [{"text": f"w{i}" + ("," if i == 9 else ""), "start": i * 0.6, "end": i * 0.6 + 0.4}
             for i in range(20)]
    parts = split_long_sentence(words)
    assert len(parts) >= 2
    assert all((p["end"] - p["start"]) <= 7.0 for p in parts)


def test_split_long_sentence_noop_when_within_limits():
    words = [{"text": "short.", "start": 0.0, "end": 0.5}]
    assert split_long_sentence(words) == [{"text": "short.", "start": 0.0, "end": 0.5}]


def test_format_cues_end_to_end_no_overlap_and_wrapped():
    words = ([{"text": "Hello", "start": 0.0, "end": 0.4}, {"text": "world.", "start": 0.4, "end": 0.9}]
             + [{"text": "This", "start": 1.0, "end": 1.2}, {"text": "is", "start": 1.2, "end": 1.3},
                {"text": "a", "start": 1.3, "end": 1.4}, {"text": "much", "start": 1.4, "end": 1.7},
                {"text": "longer", "start": 1.7, "end": 2.1}, {"text": "second", "start": 2.1, "end": 2.5},
                {"text": "sentence", "start": 2.5, "end": 3.0}, {"text": "here.", "start": 3.0, "end": 3.4}])
    cues = format_cues(words)
    assert len(cues) == 2
    for a, b in zip(cues, cues[1:]):
        assert b["start"] >= a["end"]            # no overlap after gap enforcement
    for c in cues:
        assert all(len(ln) <= 42 for ln in c["text"].split("\n"))


def test_format_cues_empty_input():
    assert format_cues([]) == []


def test_reflow_translated_wraps_and_keeps_order():
    cues = [{"text": "una frase bastante larga que necesita ajustarse en dos lineas hoy",
             "start": 0.0, "end": 1.0}]
    out = reflow_translated(cues)
    assert all(len(ln) <= 42 for ln in out[0]["text"].split("\n"))


def test_reflow_translated_rejoins_existing_newlines_before_wrapping():
    # input text arrives wrapped (\n) from the source cue; reflow must re-flow it
    cues = [{"text": "primera linea\nsegunda linea corta", "start": 0.0, "end": 5.0}]
    out = reflow_translated(cues)
    assert "\n" not in out[0]["text"] or all(len(ln) <= 42 for ln in out[0]["text"].split("\n"))
    # words preserved in order, no duplication
    assert out[0]["text"].replace("\n", " ") == "primera linea segunda linea corta"
