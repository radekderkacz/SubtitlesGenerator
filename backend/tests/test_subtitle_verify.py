from app.worker.subtitle_verify import parse_srt, check_structural, check_heuristics, aggregate, verify, _longest_repeat_run, _repeat_word_count

_GOOD = (
    "1\n00:00:01,000 --> 00:00:02,500\nHello there.\n\n"
    "2\n00:00:03,000 --> 00:00:05,000\nHow are you\ntoday?\n"
)


def test_parse_srt_basic():
    cues = parse_srt(_GOOD)
    assert len(cues) == 2
    assert cues[0] == {"index": 1, "start": 1.0, "end": 2.5, "text": "Hello there."}
    assert cues[1]["text"] == "How are you\ntoday?"


def test_structural_pass_on_good_srt():
    checks = check_structural(_GOOD, video_duration=6.0)
    assert all(c["severity"] == "ok" for c in checks), checks


def test_structural_fail_on_empty():
    checks = check_structural("", video_duration=6.0)
    assert any(c["severity"] == "fail" and c["name"] == "non_empty" for c in checks)


def test_structural_warns_on_systemic_overlap_never_fails():
    # Many overlapping cues = a systemic timing issue -> warn, but overlaps
    # never FAIL (enforce_timing allows tight sub-second overlaps).
    bad = "".join(
        f"{i}\n00:00:{i*3:02d},000 --> 00:00:{i*3+5:02d},000\nLine {i}\n\n"
        for i in range(1, 6))  # each cue (5s) overlaps the next (3s apart) -> 4 overlaps / 5
    checks = check_structural(bad, video_duration=30.0)
    assert any(c["severity"] == "warn" and c["name"] == "no_overlap" for c in checks)
    assert not any(c["severity"] == "fail" for c in checks)


def test_structural_ok_on_single_overlap():
    # One or two overlapping cues are normal tight-packing, never a warn.
    parts = [f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},500\nLine {i}\n"
             for i in range(1, 40)]
    parts[20] = "21\n00:00:19,200 --> 00:00:21,000\nLine 21\n"  # one overlap with cue 20
    checks = check_structural("\n".join(parts), video_duration=45.0)
    overlap = next(c for c in checks if c["name"] == "no_overlap")
    assert overlap["severity"] == "ok"


def test_structural_fail_on_inverted_timing():
    bad = "1\n00:00:05,000 --> 00:00:01,000\nA\n"
    checks = check_structural(bad, video_duration=6.0)
    assert any(c["severity"] == "fail" and c["name"] == "start_before_end" for c in checks)


def test_structural_warn_on_low_coverage():
    short = "1\n00:00:01,000 --> 00:00:02,000\nA\n"
    checks = check_structural(short, video_duration=600.0)
    assert any(c["name"] == "coverage" and c["severity"] in ("warn", "fail") for c in checks)


def test_structural_fail_on_zero_cues():
    checks = check_structural("not an srt at all", video_duration=6.0)
    assert any(c["name"] == "min_cues" and c["severity"] == "fail" for c in checks)


def _cues(*texts, step=2.0):
    return [{"index": i + 1, "start": i * step, "end": i * step + 1.0, "text": t}
            for i, t in enumerate(texts)]


def test_heuristics_pass_on_normal():
    checks = check_heuristics(_cues("Hello.", "How are you?", "Fine, thanks."))
    assert all(c["severity"] == "ok" for c in checks), checks


def _repeat_sev(n, text="the big bright bird"):  # 4 words = substantial
    checks = check_heuristics(_cues(*([text] * n)))
    return next(c["severity"] for c in checks if c["name"] == "repeat_loop")


def test_repeat_loop_ok_for_short_runs():
    # runs below the warn line are fine
    assert _repeat_sev(9) == "ok"


def test_repeat_loop_warns_for_moderate_runs():
    # 12-29 is suspicious-but-common: warn, don't fail
    assert _repeat_sev(15) == "warn"


def test_repeat_loop_fails_only_for_long_loops():
    # 30+ identical lines is a genuine hallucination loop
    assert _repeat_sev(35) == "fail"


def test_repeat_loop_short_line_tolerates_more():
    # one-word answers repeat naturally — don't warn until 25
    assert _repeat_sev(24, "Przepraszam.") == "ok"
    assert _repeat_sev(25, "Przepraszam.") == "warn"
    assert _repeat_sev(44, "tak") == "warn"
    assert _repeat_sev(45, "— Jimsy.") == "fail"


def test_repeat_loop_substantial_line_boundaries():
    assert _repeat_sev(11, "the big bright bird") == "ok"
    assert _repeat_sev(12, "the big bright bird") == "warn"
    assert _repeat_sev(29, "the big bright bird") == "warn"
    assert _repeat_sev(30, "the big bright bird") == "fail"


def test_repeat_loop_suppresses_short_one_word_answer():
    checks = check_heuristics(_cues(*(["Przepraszam."] * 13)))
    rl = next(c for c in checks if c["name"] == "repeat_loop")
    assert rl["severity"] == "ok"
    assert rl["repeated"]["count"] == 13


def test_repeat_loop_flags_short_line_extreme_run():
    checks = check_heuristics(_cues(*(["— Jimsy."] * 48)))
    rl = next(c for c in checks if c["name"] == "repeat_loop")
    assert rl["severity"] == "fail"


def test_heuristics_warn_on_artifact_phrase():
    checks = check_heuristics(_cues("Hello.", "Thanks for watching!"))
    assert any(c["name"] == "artifact_phrase" and c["severity"] in ("warn", "fail") for c in checks)


def test_silence_gaps_is_informational_not_a_warn():
    # Long no-dialogue stretches are normal in film/TV, so silence_gaps reports
    # the gap but stays 'ok' (never drives the verdict).
    cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "A"},
            {"index": 2, "start": 120.0, "end": 121.0, "text": "B"}]
    checks = check_heuristics(cues)
    gap = next(c for c in checks if c["name"] == "silence_gaps")
    assert gap["severity"] == "ok"
    assert "gap" in gap["detail"]  # still surfaced for the user


def test_heuristics_warn_on_cps_when_many_fast():
    # a whole batch of rushed cues = systemic problem -> warn
    cues = [{"index": i + 1, "start": i, "end": i + 0.3, "text": "x" * 60} for i in range(20)]
    checks = check_heuristics(cues)
    assert any(c["name"] == "reading_speed" and c["severity"] == "warn" for c in checks)


def test_heuristics_ok_on_few_fast_cues():
    # only 1 rushed cue in 50 (2%, below the fraction gate) -> not a warn
    cues = [{"index": i + 1, "start": i * 3.0, "end": i * 3.0 + 2.0, "text": "normal line"} for i in range(50)]
    cues[10] = {"index": 11, "start": 30.0, "end": 30.3, "text": "x" * 60}  # one very fast cue
    checks = check_heuristics(cues)
    assert any(c["name"] == "reading_speed" and c["severity"] == "ok" for c in checks)


_GOOD_V = (
    "1\n00:00:01,000 --> 00:00:02,500\nHello there.\n\n"
    "2\n00:00:03,000 --> 00:00:05,000\nHow are you today?\n"
)


def test_aggregate_pass_when_all_ok():
    v = aggregate([{"layer": "structural", "name": "x", "severity": "ok", "detail": ""}])
    assert v["status"] == "pass" and v["score"] == 100


def test_aggregate_fail_dominates_on_structural_fail():
    checks = [{"layer": "structural", "name": "non_empty", "severity": "fail", "detail": ""},
              {"layer": "heuristic", "name": "x", "severity": "ok", "detail": ""}]
    assert aggregate(checks)["status"] == "fail"


def test_aggregate_warn_on_heuristic_warn_only():
    checks = [{"layer": "structural", "name": "x", "severity": "ok", "detail": ""},
              {"layer": "heuristic", "name": "y", "severity": "warn", "detail": ""}]
    assert aggregate(checks)["status"] == "warn"


def test_verify_pass_on_good_srt_without_llm():
    v = verify(_GOOD_V, video_duration=6.0, model_cfg=None)
    assert v["status"] == "pass"
    assert any(c["layer"] == "semantic" and c["severity"] == "skipped" for c in v["report"]["checks"])


def test_verify_fail_on_repeat_loop_srt():
    # 35 identical multi-word cues = a genuine hallucination loop -> fail
    loop = "".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\nSame thing over again.\n\n" for i in range(1, 36))
    v = verify(loop, video_duration=40.0, model_cfg=None)
    assert v["status"] == "fail"


from pathlib import Path

_FX = Path(__file__).parent / "fixtures"


def test_real_known_good_srt_passes():
    v = verify((_FX / "srt_known_good.srt").read_text(encoding="utf-8"),
               video_duration=2520.0, model_cfg=None)
    assert v["status"] in ("pass", "warn"), v["report"]["summary"]


def test_hallucination_srt_fails():
    v = verify((_FX / "srt_hallucination.srt").read_text(encoding="utf-8"),
               video_duration=600.0, model_cfg=None)
    assert v["status"] == "fail"


def test_longest_repeat_run_returns_text_time_count():
    cues = [{"index": i + 1, "start": i * 2.0, "end": i * 2.0 + 1.0, "text": "— Jimsy."} for i in range(5)]
    assert _longest_repeat_run(cues) == {"text": "— Jimsy.", "start": 0.0, "end": 9.0, "count": 5}


def test_longest_repeat_run_none_without_repetition():
    cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "A"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "B"}]
    assert _longest_repeat_run(cues) is None


def test_repeat_loop_check_includes_repeated_evidence():
    cues = [{"index": i + 1, "start": i, "end": i + 0.9, "text": "Same."} for i in range(13)]
    rl = next(c for c in check_heuristics(cues) if c["name"] == "repeat_loop")
    assert rl["repeated"]["text"] == "Same."
    assert rl["repeated"]["count"] == 13


def test_repeat_loop_check_omits_repeated_when_none():
    cues = [{"index": i + 1, "start": i, "end": i + 0.9, "text": f"line {i}"} for i in range(4)]
    rl = next(c for c in check_heuristics(cues) if c["name"] == "repeat_loop")
    assert "repeated" not in rl


def test_repeat_word_count_strips_dialogue_dash():
    assert _repeat_word_count("— Jimsy.") == 1
    assert _repeat_word_count("Przepraszam.") == 1
    assert _repeat_word_count("I am very sorry") == 4
    assert _repeat_word_count("") == 0
    assert _repeat_word_count("- Yes.") == 1


# ---------------------------------------------------------------------------
# WS4 (2026-07 audit): normalized repeats, loop vocabulary, alignment,
# coverage v2, blank cues, artifact tiers, metrics
# ---------------------------------------------------------------------------

def _cue(i, start, end, text):
    return {"index": i, "start": start, "end": end, "text": text}


def _mk_cues(texts, dur=2.0, gap=0.5):
    out, t = [], 0.0
    for i, txt in enumerate(texts, start=1):
        out.append(_cue(i, t, t + dur, txt))
        t += dur + gap
    return out


def test_repeat_run_matches_normalized_text():
    # punctuation drift must not reset the run ("that." vs "that")
    cues = _mk_cues(["I know that."] * 20 + ["I know that"] * 20)
    from app.worker.subtitle_verify import _longest_repeat_run
    run = _longest_repeat_run(cues)
    assert run["count"] == 40


def test_music_refrains_do_not_join_repeat_runs():
    cues = _mk_cues(["♪ Na na na na ♪"] * 33)
    checks = check_heuristics(cues)
    repeat = next(c for c in checks if c["name"] == "repeat_loop")
    assert repeat["severity"] == "ok"


def test_loop_vocabulary_catches_alternating_hallucination():
    texts = ["I don't know." if i % 2 == 0 else "What do you mean?" for i in range(60)]
    checks = check_heuristics(_mk_cues(texts))
    loop = next(c for c in checks if c["name"] == "loop_vocabulary")
    assert loop["severity"] == "fail"


def test_loop_vocabulary_catches_three_cycle():
    texts = [["Yes.", "No.", "Maybe."][i % 3] for i in range(90)]
    checks = check_heuristics(_mk_cues(texts))
    loop = next(c for c in checks if c["name"] == "loop_vocabulary")
    assert loop["severity"] == "fail"


def test_loop_vocabulary_ok_on_normal_dialogue():
    texts = [f"This is a perfectly normal line number {i}." for i in range(80)]
    checks = check_heuristics(_mk_cues(texts))
    loop = next(c for c in checks if c["name"] == "loop_vocabulary")
    assert loop["severity"] == "ok"


def test_loop_vocabulary_exempts_songs():
    texts = (["♪ La la la ♪", "♪ Na na na ♪"] * 20)
    checks = check_heuristics(_mk_cues(texts))
    loop = next(c for c in checks if c["name"] == "loop_vocabulary")
    assert loop["severity"] == "ok"


def test_coverage_uses_max_end_and_upper_bound():
    from app.worker.subtitle_verify import check_structural
    # subs run 2h past a 10-min video → must not pass
    srt = "1\n00:00:01,000 --> 00:00:03,000\nHi.\n\n2\n02:00:00,000 --> 02:00:05,000\nGhost.\n"
    checks = check_structural(srt, video_duration=600.0)
    cov = next(c for c in checks if c["name"] == "coverage")
    assert cov["severity"] in ("warn", "fail")


def test_monotonic_order_warns_on_scrambled_cues():
    from app.worker.subtitle_verify import check_structural
    srt = ("1\n00:01:00,000 --> 00:01:02,000\nLate.\n\n"
           "2\n00:00:10,000 --> 00:00:12,000\nEarly.\n")
    checks = check_structural(srt, video_duration=None)
    mono = next(c for c in checks if c["name"] == "monotonic_order")
    assert mono["severity"] == "warn"


def test_blank_cues_fail_when_pervasive():
    cues = _mk_cues([""] * 5 + ["Real line here."] * 5)
    checks = check_heuristics(cues)
    blank = next(c for c in checks if c["name"] == "blank_cues")
    assert blank["severity"] == "fail"


def test_blank_cues_ok_when_absent():
    cues = _mk_cues(["A line.", "Another line."])
    checks = check_heuristics(cues)
    blank = next(c for c in checks if c["name"] == "blank_cues")
    assert blank["severity"] == "ok"


def test_weak_artifact_in_dialogue_mid_film_is_clean():
    texts = [f"Normal dialogue line {i}." for i in range(200)]
    texts[100] = "I subscribe to that newspaper, always have."
    checks = check_heuristics(_mk_cues(texts))
    art = next(c for c in checks if c["name"] == "artifact_phrase")
    assert art["severity"] == "ok"


def test_strong_artifact_still_warns():
    cues = _mk_cues(["Real line.", "Subtitles by the Amara.org community"])
    checks = check_heuristics(cues)
    art = next(c for c in checks if c["name"] == "artifact_phrase")
    assert art["severity"] == "warn"


def test_alignment_fails_on_dropped_lines():
    from app.worker.subtitle_verify import check_alignment
    target = _mk_cues([f"Line {i}." for i in range(40)])
    source = _mk_cues([f"Src {i}." for i in range(400)])
    checks = check_alignment(target, source)
    align = next(c for c in checks if c["name"] == "alignment")
    assert align["severity"] == "fail"


def test_alignment_ok_on_reflow_split():
    from app.worker.subtitle_verify import check_alignment
    # WS1 reflow legitimately splits expanded translations: 120 vs 100 is fine
    target = _mk_cues([f"Linia przetłumaczona {i}." for i in range(120)])
    source = _mk_cues([f"Translated line {i}." for i in range(100)])
    checks = check_alignment(target, source)
    align = next(c for c in checks if c["name"] == "alignment")
    assert align["severity"] == "ok"


def test_pair_cues_by_time_aligns_mismatched_counts():
    from app.worker.subtitle_verify import pair_cues_by_time
    target = [_cue(i, i * 10.0, i * 10.0 + 2, f"T{i}") for i in range(10)]
    source = [_cue(i, i * 5.0, i * 5.0 + 2, f"S{i}") for i in range(20)]
    pairs = pair_cues_by_time(target[:3], source)
    # T0@0s→S0@0s, T1@10s→S2@10s, T2@20s→S4@20s
    assert [(s["text"], t["text"]) for s, t in pairs] == [("S0", "T0"), ("S2", "T1"), ("S4", "T2")]


def test_verify_includes_metrics():
    srt = ("1\n00:00:01,000 --> 00:00:03,000\nHello there.\n\n"
           "2\n00:00:04,000 --> 00:00:06,500\nHow are you today?\n")
    out = verify(srt, video_duration=10.0)
    m = out["report"]["metrics"]
    assert m["cue_count"] == 2
    assert 0.6 < m["coverage_ratio"] <= 0.7
    assert m["cps_max"] > 0
