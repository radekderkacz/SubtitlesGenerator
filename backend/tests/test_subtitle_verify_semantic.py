from unittest.mock import MagicMock, patch

from app.worker.subtitle_verify import sample_cues, build_judge_prompt, parse_judge_response
from app.worker.subtitle_verify_judge import judge_semantics


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


def _judge_mock_client(content: str):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"choices": [{"message": {"content": content}}]}
    client = MagicMock()
    client.post.return_value = resp
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    return client


def test_judge_request_pins_zero_temperature():
    cues = [{"index": 1, "start": 0.0, "end": 1.0, "text": "Hello"}]
    mock_client = _judge_mock_client('{"score": 90, "verdict": "ok", "issues": []}')
    with patch("httpx.Client", return_value=mock_client):
        judge_semantics(cues, None, {"mapped_model": "ollama/x", "base_url": "http://x"})
    body = mock_client.post.call_args.kwargs["json"]
    assert body["temperature"] == 0


def test_judge_outage_with_configured_model_warns_not_passes():
    """WS4: a configured-but-unreachable judge must surface as warn —
    'skipped' ranks as ok and silently upgraded outages to passes."""
    from app.worker.subtitle_verify_judge import judge_semantics
    cues = [{"index": 1, "start": 0.0, "end": 2.0, "text": "Hello."}]
    # mapped_model resolves but the endpoint is unreachable -> exception path
    check = judge_semantics(cues, None, {"mapped_model": "openai/x", "base_url": "http://127.0.0.1:1"})
    assert check["severity"] == "warn"
    assert "unverified" in check["detail"]
