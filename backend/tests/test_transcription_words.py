import json
from pathlib import Path

from app.worker.cue_timing import extract_words

_FIXTURES = Path(__file__).parent / "fixtures"
_SYNTHETIC = _FIXTURES / "words_response_synthetic.json"
_REAL_SEGMENT = _FIXTURES / "fws_segment_response.json"


def test_extract_words_from_synthetic_response():
    data = json.loads(_SYNTHETIC.read_text())
    words = extract_words(data)
    assert len(words) > 0
    for w in words:
        assert set(w) == {"text", "start", "end"}
        assert isinstance(w["text"], str) and w["text"] == w["text"].strip()
        assert w["text"] != ""
        assert isinstance(w["start"], float) and isinstance(w["end"], float)
        assert w["end"] >= w["start"]
    # leading-space stripping + punctuation retention
    assert [w["text"] for w in words] == ["Hello", "there.", "How", "are", "you?"]
    # monotonic non-decreasing starts
    starts = [w["start"] for w in words]
    assert starts == sorted(starts)


def test_extract_words_real_segment_response_has_no_words():
    # The live server returns segment-level only — extract_words must yield [].
    data = json.loads(_REAL_SEGMENT.read_text())
    assert extract_words(data) == []


def test_extract_words_handles_missing_words_key():
    assert extract_words({"segments": [{"start": 0, "end": 1, "text": "hi"}]}) == []
    assert extract_words({}) == []


def test_extract_words_top_level_words_array():
    # A word-capable server may return a flat top-level words array instead.
    data = {"words": [
        {"word": " Go", "start": 0.0, "end": 0.3},
        {"word": " now.", "start": 0.3, "end": 0.7},
    ]}
    assert extract_words(data) == [
        {"text": "Go", "start": 0.0, "end": 0.3},
        {"text": "now.", "start": 0.3, "end": 0.7},
    ]


def test_extract_words_drops_empty_and_untimed_tokens():
    data = {"words": [
        {"word": "  ", "start": 0.0, "end": 0.1},          # whitespace only
        {"word": "ok", "start": None, "end": 0.5},          # missing start
        {"word": "good", "start": 0.5, "end": None},        # missing end
        {"word": "keep", "start": 0.6, "end": 0.9},
    ]}
    assert extract_words(data) == [{"text": "keep", "start": 0.6, "end": 0.9}]


def _patch_remote(monkeypatch, response_body, captured=None):
    from app.worker import tasks

    class _Resp:
        def raise_for_status(self): pass  # 2xx — nothing to raise
        def json(self): return response_body

    class _Client:
        def __init__(self, *a, **k): pass  # no real connection in tests
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, files=None, data=None):
            if captured is not None:
                captured["data"] = data
            return _Resp()

    monkeypatch.setattr(tasks.httpx, "Client", _Client)
    monkeypatch.setattr(tasks, "_compress_audio_for_remote", lambda p: p)
    monkeypatch.setattr(tasks, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(tasks, "_wait_remote_ready", lambda url, **k: None)
    monkeypatch.setattr(tasks.os, "remove", lambda p: None)
    return tasks


def test_transcription_requests_word_granularity_dict_with_list_form(monkeypatch, tmp_path):
    captured = {}
    tasks = _patch_remote(
        monkeypatch,
        {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]},
        captured,
    )
    (tmp_path / "a.wav").write_bytes(b"AUDIO")
    tasks._run_transcription_remote_blocking(str(tmp_path / "a.wav"), "http://x", "m", None)
    # dict-with-list form (the list-of-tuples form breaks httpx multipart)
    assert captured["data"]["timestamp_granularities[]"] == ["segment", "word"]
    assert captured["data"]["response_format"] == "verbose_json"
    assert captured["data"]["model"] == "m"


def test_transcription_result_includes_normalized_words(monkeypatch, tmp_path):
    fixture = json.loads(_SYNTHETIC.read_text())
    tasks = _patch_remote(monkeypatch, fixture)
    (tmp_path / "a.wav").write_bytes(b"AUDIO")
    result = tasks._run_transcription_remote_blocking(str(tmp_path / "a.wav"), "http://x", "m", None)
    assert "words" in result and len(result["words"]) > 0
    assert set(result["words"][0]) == {"text", "start", "end"}


def test_transcription_result_words_empty_for_segment_only_server(monkeypatch, tmp_path):
    real = json.loads(_REAL_SEGMENT.read_text())
    tasks = _patch_remote(monkeypatch, real)
    (tmp_path / "a.wav").write_bytes(b"AUDIO")
    result = tasks._run_transcription_remote_blocking(str(tmp_path / "a.wav"), "http://x", "m", None)
    assert result["words"] == []
    assert len(result["segments"]) == 1
