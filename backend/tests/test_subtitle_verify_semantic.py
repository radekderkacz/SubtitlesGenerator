from app.worker.subtitle_verify import sample_cues, build_judge_prompt, parse_judge_response


def _cues(n):
    return [{"index": i + 1, "start": i, "end": i + 0.9, "text": f"line {i}"} for i in range(n)]


def test_sample_cues_caps_and_preserves_order():
    s = sample_cues(_cues(100), k=25)
    assert len(s) == 25
    assert [c["index"] for c in s] == sorted(c["index"] for c in s)


def test_sample_cues_returns_all_when_fewer():
    assert len(sample_cues(_cues(10), k=25)) == 10


def test_build_judge_prompt_coherence_only():
    system, user = build_judge_prompt(_cues(3), source_cues=None)
    assert "coheren" in system.lower()
    assert "line 0" in user
    assert "faithful" not in user.lower()


def test_build_judge_prompt_with_translation_faithfulness():
    tgt = _cues(3)
    src = [{"index": i + 1, "start": i, "end": i + 0.9, "text": f"src {i}"} for i in range(3)]
    system, user = build_judge_prompt(tgt, source_cues=src)
    assert "faithful" in (system + user).lower()
    assert "src 0" in user and "line 0" in user


def test_parse_judge_response_ok():
    raw = '{"score": 90, "verdict": "ok", "issues": []}'
    c = parse_judge_response(raw)
    assert c["severity"] == "ok" and "90" in c["detail"]


def test_parse_judge_response_flags_low_score():
    raw = '{"score": 30, "verdict": "bad", "issues": ["gibberish in cue 4"]}'
    c = parse_judge_response(raw)
    assert c["severity"] == "fail"
    assert "gibberish" in c["detail"]


def test_parse_judge_response_tolerates_garbage():
    c = parse_judge_response("the model rambled with no json")
    assert c["severity"] == "skipped"


def test_parse_judge_handles_markdown_fences():
    # gemma3's actual format: ```json\n{...}\n```
    raw = '```json\n{"score": 95, "verdict": "ok", "issues": []}\n```'
    c = parse_judge_response(raw)
    assert c["severity"] == "ok" and "95" in c["detail"]


def test_parse_judge_handles_trailing_prose():
    raw = 'Sure, here is my assessment: {"score": 40, "verdict": "bad", "issues": ["x"]} Hope it helps!'
    c = parse_judge_response(raw)
    assert c["severity"] == "fail" and "40" in c["detail"]


def test_parse_judge_recovers_score_from_malformed_json():
    # unescaped double-quotes inside an issue break json.loads -> recover the score
    raw = '{"score": 55, "verdict": "ok", "issues": ["the word "yard" reads oddly"]}'
    c = parse_judge_response(raw)
    assert c["severity"] == "warn"           # 55 -> warn
    assert "55" in c["detail"]
