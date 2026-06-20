from app.worker.subtitle_verify import parse_srt, check_structural, check_heuristics, aggregate, verify

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


def test_structural_warns_not_fails_on_overlap():
    # enforce_timing intentionally allows sub-second overlaps in packed runs, so
    # the verifier warns (not fails) on overlapping cues.
    bad = ("1\n00:00:01,000 --> 00:00:05,000\nA\n\n"
           "2\n00:00:03,000 --> 00:00:04,000\nB\n")
    checks = check_structural(bad, video_duration=6.0)
    assert any(c["severity"] == "warn" and c["name"] == "no_overlap" for c in checks)
    assert not any(c["severity"] == "fail" for c in checks)


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


def test_heuristics_fail_on_repeat_loop():
    checks = check_heuristics(_cues(*(["Same line."] * 8)))
    assert any(c["name"] == "repeat_loop" and c["severity"] == "fail" for c in checks)


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
    loop = "".join(
        f"{i}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\nSame.\n\n" for i in range(1, 9))
    v = verify(loop, video_duration=10.0, model_cfg=None)
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
