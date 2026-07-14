from app.worker.cue_timing import (
    extract_words,
    merge_short_cues,
    apply_invariants,
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


# --- WS1: apply_invariants (output safety net) ---------------------------------

def test_invariants_sorts_out_of_order_cues():
    cues = [{"text": "b", "start": 5.0, "end": 6.0}, {"text": "a", "start": 0.0, "end": 1.0}]
    out = apply_invariants(cues)
    assert [c["text"] for c in out] == ["a", "b"]


def test_invariants_trims_overlap_to_min_gap():
    cues = [{"text": "a", "start": 0.0, "end": 5.0}, {"text": "b", "start": 2.0, "end": 6.0}]
    out = apply_invariants(cues)
    assert out[0]["end"] <= out[1]["start"] - 0.08 + 1e-9


def test_invariants_merges_unavoidable_overlap():
    cues = [{"text": "a", "start": 1.0, "end": 1.05}, {"text": "b", "start": 1.0, "end": 3.0}]
    out = apply_invariants(cues)
    assert len(out) == 1 and out[0]["text"] == "a b"


def test_invariants_repairs_nonpositive_duration():
    out = apply_invariants([{"text": "a", "start": 2.0, "end": 1.0}])
    assert out[0]["end"] > out[0]["start"]


def test_invariants_drops_empty_text():
    assert apply_invariants([{"text": "  ", "start": 0.0, "end": 1.0}]) == []


# --- WS1: enforce_timing clamp order --------------------------------------------

def test_enforce_timing_never_creates_overlap_via_min_duration():
    # Audit probe: min-duration extension used to cross next.start when the
    # ceiling fell at-or-before the cue's own start.
    cues = [{"text": "hi", "start": 1.0, "end": 1.05},
            {"text": "next", "start": 1.05, "end": 3.0}]
    out = enforce_timing(cues)
    assert (out[0]["end"] <= out[1]["start"] - 0.08 + 1e-9
            or out[0]["end"] <= out[0]["start"] + 1e-9)


def test_enforce_timing_ceiling_beats_min_duration():
    cues = [{"text": "Hi.", "start": 0.0, "end": 0.054},
            {"text": "Then a considerably longer sentence follows.", "start": 0.134, "end": 3.0}]
    out = enforce_timing(cues)
    assert out[0]["end"] <= 0.134 - 0.08 + 1e-9


# --- WS1: merge_short_cues -------------------------------------------------------

def test_rapid_one_word_answers_merge():
    cues = [{"text": "Hi.", "start": 0.0, "end": 0.2},
            {"text": "Yes.", "start": 0.2, "end": 0.4},
            {"text": "Go.", "start": 0.4, "end": 0.6}]
    out = merge_short_cues(cues)
    assert len(out) == 1 and out[0]["text"] == "Hi. Yes. Go."
    assert out[0]["start"] == 0.0 and out[0]["end"] == 0.6


def test_merge_respects_char_cap():
    a = {"text": "x" * 60, "start": 0.0, "end": 0.4}
    b = {"text": "y" * 60, "start": 0.45, "end": 0.8}
    assert len(merge_short_cues([a, b])) == 2


def test_merge_skips_distant_neighbors():
    # 4.7s gap: the short cue can linger into silence instead of merging
    cues = [{"text": "Hi.", "start": 0.0, "end": 0.3},
            {"text": "Later.", "start": 5.0, "end": 5.3}]
    assert len(merge_short_cues(cues)) == 2


def test_readable_cues_untouched():
    cues = [{"text": "A normal line here.", "start": 0.0, "end": 2.0},
            {"text": "Another normal one.", "start": 2.5, "end": 4.5}]
    assert merge_short_cues(cues) == cues


# --- WS1: reflow re-splits + extract_words sanity ---------------------------------

def test_reflow_translated_resplits_expanded_text():
    # Audit probe: a 150-char translation used to wrap to 4 lines in one cue
    cues = [{"text": "a" * 150, "start": 0.0, "end": 6.0},
            {"text": "next", "start": 8.0, "end": 9.0}]
    out = reflow_translated(cues)
    assert all(len(c["text"].split("\n")) <= 2 for c in out)
    assert len(out) >= 3


def test_extract_words_sorts_and_repairs():
    resp = {"words": [{"word": " world", "start": 1.0, "end": 1.5},
                      {"word": " Hello", "start": 0.0, "end": 0.5},
                      {"word": " bad", "start": 3.0, "end": 2.0}]}
    words = extract_words(resp)
    assert [w["text"] for w in words] == ["Hello", "world", "bad"]
    assert all(w["end"] >= w["start"] for w in words)


# --- WS1: break constraints + hard wrap -------------------------------------------

def test_split_long_sentence_no_orphan_fragments():
    # A leading word then a big pause used to orphan "A" as its own 0.1s cue
    words = ([_w("A", 0.0, 0.1)] +
             [_w(f"w{i}", 1.0 + i * 0.15, 1.0 + i * 0.15 + 0.1) for i in range(30)])
    cues = split_long_sentence(words)
    assert len(cues) >= 2
    assert all(len(c["text"]) >= 10 for c in cues)


def test_wrap_hard_breaks_unspaced_text():
    wrapped = wrap_lines("十" * 60)
    assert all(len(line) <= 42 for line in wrapped.split("\n"))


def test_wrap_hard_breaks_single_long_token_mixed():
    wrapped = wrap_lines("see https://" + "x" * 70 + " now")
    assert all(len(line) <= 42 for line in wrapped.split("\n"))
