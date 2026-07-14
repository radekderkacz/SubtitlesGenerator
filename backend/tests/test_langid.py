"""Output language-ID gate (WS10, 2026-07 audit). Core logic tested with an
injected detector; the real fastText model only ships in the worker image."""
import pytest

from app.worker.langid import batch_language_suspect, detect_language, language_check


def _fake(lang, score=0.95):
    return lambda text: (lang, score)


def test_detect_language_short_text_is_none():
    assert detect_language("Hi.", detect_fn=_fake("en")) is None


def test_detect_language_low_confidence_is_none():
    long_text = "word " * 20
    assert detect_language(long_text, detect_fn=_fake("en", 0.3)) is None


def test_batch_suspect_when_output_reads_as_source():
    texts = ["This is still English text, clearly not translated at all."] * 3
    assert batch_language_suspect(texts, "pl", "en", detect_fn=_fake("en")) is True


def test_batch_ok_when_output_reads_as_target():
    texts = ["To jest poprawnie przetłumaczony polski tekst, bez wątpienia."] * 3
    assert batch_language_suspect(texts, "pl", "en", detect_fn=_fake("pl")) is False


def test_batch_third_language_left_to_verification():
    texts = ["Un texto en otro idioma completamente distinto del esperado."] * 3
    assert batch_language_suspect(texts, "pl", "en", detect_fn=_fake("es")) is False


def test_batch_no_op_without_languages():
    assert batch_language_suspect(["x" * 100], None, "en", detect_fn=_fake("en")) is False
    assert batch_language_suspect(["x" * 100], "en", "en", detect_fn=_fake("en")) is False


def test_language_check_fails_on_mismatch():
    cues = [{"text": "This is definitely English output that should be Polish."}] * 10
    check = language_check(cues, "pl", detect_fn=_fake("en"))
    assert check["severity"] == "fail"
    assert "expected 'pl'" in check["detail"]


def test_language_check_ok_on_match_and_unavailable():
    cues = [{"text": "Zdecydowanie polski tekst w napisach do filmu."}] * 10
    assert language_check(cues, "pl", detect_fn=_fake("pl"))["severity"] == "ok"
    assert language_check(cues, "pl", detect_fn=lambda t: None)["severity"] == "ok"
    assert language_check(cues, None)["severity"] == "ok"


def test_real_model_if_installed():
    pytest.importorskip("fast_langdetect")
    out = detect_language("This is clearly an English sentence about movies and subtitles.")
    assert out is not None and out[0] == "en"


def test_loader_adapts_the_1x_list_api(monkeypatch):
    """fast-langdetect 1.x returns a ranked LIST and takes model=, not
    low_memory= — the loader must adapt (caught live on the deployed worker,
    2026-07-14)."""
    import sys
    import types

    calls = {}

    def fake_detect(text, *, model=None, k=1, threshold=0.0, config=None):
        calls["model"] = model
        return [{"lang": "EN", "score": 0.97}]

    fake_mod = types.ModuleType("fast_langdetect")
    fake_mod.detect = fake_detect
    monkeypatch.setitem(sys.modules, "fast_langdetect", fake_mod)

    import app.worker.langid as L
    monkeypatch.setattr(L, "_detector", None)
    monkeypatch.setattr(L, "_detector_failed", False)
    fn = L._load_detector()
    assert fn is not None
    assert fn("hello world") == ("en", 0.97)
    assert calls["model"] == "lite"  # never the auto-downloading default
