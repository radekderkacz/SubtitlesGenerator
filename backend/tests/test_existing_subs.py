"""Existing-subtitle discovery, SDH stripping, and the worker gate."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.worker import tasks
from app.worker.existing_subs import (
    SubCandidate,
    find_sidecar_candidates,
    probe_embedded_candidates,
    rank_candidates,
    strip_sdh,
)

_SRT = (
    "1\n00:00:01,000 --> 00:00:03,000\nHello there, how are you doing today?\n\n"
    "2\n00:00:04,000 --> 00:00:06,500\nI am doing quite well, thank you very much.\n"
)


# ---------------------------------------------------------------------------
# Sidecar discovery
# ---------------------------------------------------------------------------

def test_sidecar_language_variants(tmp_path):
    video = tmp_path / "Movie.mkv"
    video.touch()
    for name in ("Movie.en.srt", "Movie.eng.srt", "Movie.srt",
                 "Movie.en.forced.srt", "Movie.en.sdh.srt", "Movie.pl.srt",
                 "Other.en.srt"):
        (tmp_path / name).write_text(_SRT)
    cands = find_sidecar_candidates(str(video), exclude_paths=set())
    by_name = {c.path.rsplit("/", 1)[-1]: c for c in cands}
    assert "Movie.en.forced.srt" not in by_name          # forced disqualified
    assert "Other.en.srt" not in by_name                 # different stem
    assert by_name["Movie.en.srt"].language == "en"
    assert by_name["Movie.eng.srt"].language == "en"     # iso639-2 normalized
    assert by_name["Movie.en.sdh.srt"].language == "en"  # sdh flag ignored
    assert by_name["Movie.srt"].language is None         # no tag
    assert by_name["Movie.pl.srt"].language == "pl"


def test_sidecar_excludes_own_target_output(tmp_path):
    video = tmp_path / "Movie.mkv"
    video.touch()
    (tmp_path / "Movie.pl.srt").write_text(_SRT)
    cands = find_sidecar_candidates(str(video), exclude_paths={str(tmp_path / "Movie.pl.srt")})
    assert cands == []


# ---------------------------------------------------------------------------
# Embedded discovery (mocked ffprobe)
# ---------------------------------------------------------------------------

def _probe_result(streams):
    return {"streams": streams}


def _fake_ffmpeg(monkeypatch, probe):
    import sys, types
    fake = types.ModuleType("ffmpeg")
    fake.probe = probe
    monkeypatch.setitem(sys.modules, "ffmpeg", fake)


def test_embedded_filters_and_indexing(monkeypatch):
    streams = [
        {"codec_type": "video", "codec_name": "h264"},
        {"codec_type": "subtitle", "codec_name": "hdmv_pgs_subtitle",
         "tags": {"language": "eng"}},                      # bitmap: skipped, still s:0
        {"codec_type": "subtitle", "codec_name": "subrip",
         "tags": {"language": "eng"}, "disposition": {"forced": 1}},  # forced: skipped, s:1
        {"codec_type": "subtitle", "codec_name": "subrip",
         "tags": {"language": "pol"}, "disposition": {"forced": 0}},  # s:2 ✓
        {"codec_type": "subtitle", "codec_name": "ass"},               # s:3 ✓ no tag
    ]
    _fake_ffmpeg(monkeypatch, lambda p: _probe_result(streams))
    cands = probe_embedded_candidates("/media/Movie.mkv")
    assert [(c.stream_index, c.language) for c in cands] == [(2, "pl"), (3, None)]


def test_embedded_probe_failure_is_empty(monkeypatch):
    def boom(p):
        raise RuntimeError("no such file")
    _fake_ffmpeg(monkeypatch, boom)
    assert probe_embedded_candidates("/gone.mkv") == []


def test_embedded_missing_ffmpeg_lib_is_empty():
    # Discovery must fail soft even if ffmpeg-python is absent entirely.
    assert probe_embedded_candidates("/media/Movie.mkv") == []


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def test_rank_prefers_source_then_target_then_known_then_sidecar():
    cands = [
        SubCandidate(kind="embedded", stream_index=0, language=None),
        SubCandidate(kind="embedded", stream_index=1, language="pl"),
        SubCandidate(kind="sidecar", path="/m/a.de.srt", language="de"),
        SubCandidate(kind="sidecar", path="/m/a.en.srt", language="en"),
        SubCandidate(kind="embedded", stream_index=2, language="en"),
    ]
    ranked = rank_candidates(cands, source_hint="en", target_language="pl")
    assert [(c.kind, c.language) for c in ranked] == [
        ("sidecar", "en"), ("embedded", "en"),   # source-language matches first
        ("embedded", "pl"),                       # then target (no-op translation)
        ("sidecar", "de"),                        # then known language
        ("embedded", None),                       # unknown last
    ]


# ---------------------------------------------------------------------------
# SDH stripping
# ---------------------------------------------------------------------------

def test_strip_sdh_removes_markup():
    cues = [
        {"start": 1, "end": 2, "text": "[door slams]\nJOHN: Hello there."},
        {"start": 3, "end": 4, "text": "(SIGHS) I know."},
        {"start": 5, "end": 6, "text": "♪ dramatic music ♪"},
        {"start": 7, "end": 8, "text": "Normal line."},
    ]
    out = strip_sdh(cues)
    assert [c["text"] for c in out] == ["Hello there.", "I know.", "Normal line."]


def test_strip_sdh_keeps_lowercase_colon_lines():
    # "Meet me at 10:30" must not be treated as a speaker label.
    cues = [{"start": 1, "end": 2, "text": "Meet me at 10:30 sharp."}]
    assert strip_sdh(cues)[0]["text"] == "Meet me at 10:30 sharp."


# ---------------------------------------------------------------------------
# Worker gate (tasks._try_existing_subs and friends)
# ---------------------------------------------------------------------------

def _gate_job(tmp_path, **kw):
    base = dict(id="j1", file_path=str(tmp_path / "Movie.mkv"),
                source_language="auto", target_language="pl",
                use_existing_subs=True, source_srt_path=None)
    base.update(kw)
    return type("J", (), base)()


def test_gate_disabled_by_job_flag(tmp_path):
    job = _gate_job(tmp_path, use_existing_subs=False)
    assert tasks._try_existing_subs(job, "j1", "log", None) is None


def test_gate_kill_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBGEN_DISABLE_EXISTING_SUBS", "1")
    job = _gate_job(tmp_path)
    assert tasks._try_existing_subs(job, "j1", "log", None) is None


def test_gate_accepts_verified_sidecar(monkeypatch, tmp_path):
    (tmp_path / "Movie.mkv").touch()
    (tmp_path / "Movie.en.srt").write_text(_SRT)
    job = _gate_job(tmp_path, source_language="en")
    monkeypatch.setattr(tasks, "_probe_duration", lambda p: None)
    monkeypatch.setattr(tasks, "_existing_subs_verdict", lambda c, d, r: "warn")
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("en", 0.99))
    monkeypatch.setattr(tasks, "_write_log", MagicMock())

    out = tasks._try_existing_subs(job, "j1", "log", None)
    assert out is not None
    assert out["language"] == "en"
    assert out["origin_path"] == str(tmp_path / "Movie.en.srt")
    assert len(out["existing_cues"]) == 2


def test_gate_rejects_failing_candidates(monkeypatch, tmp_path):
    (tmp_path / "Movie.mkv").touch()
    (tmp_path / "Movie.en.srt").write_text(_SRT)
    job = _gate_job(tmp_path, source_language="en")
    monkeypatch.setattr(tasks, "_probe_duration", lambda p: None)
    monkeypatch.setattr(tasks, "_existing_subs_verdict", lambda c, d, r: "fail")
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("en", 0.99))
    monkeypatch.setattr(tasks, "_write_log", MagicMock())

    assert tasks._try_existing_subs(job, "j1", "log", None) is None


def test_gate_no_candidates(monkeypatch, tmp_path):
    (tmp_path / "Movie.mkv").touch()
    _fake_ffmpeg(monkeypatch, lambda p: {"streams": []})
    job = _gate_job(tmp_path)
    assert tasks._try_existing_subs(job, "j1", "log", None) is None


def test_candidate_language_rejects_hint_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("fr", 0.99))
    job = _gate_job(tmp_path, source_language="en", target_language="pl")
    cues = [{"text": "Bonjour tout le monde, comment allez-vous?"}]
    lang, reason = tasks._candidate_language(cues, "fr", job)
    assert lang is None
    assert "fr" in reason  # the rejection says what WAS detected


def test_candidate_language_accepts_target_match(monkeypatch, tmp_path):
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("pl", 0.99))
    job = _gate_job(tmp_path, source_language="en", target_language="pl")
    cues = [{"text": "Dzień dobry wszystkim, jak się macie?"}]
    assert tasks._candidate_language(cues, None, job) == ("pl", None)


def test_candidate_language_auto_accepts_any_detected(monkeypatch, tmp_path):
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("de", 0.99))
    job = _gate_job(tmp_path, source_language="auto", target_language=None)
    cues = [{"text": "Guten Tag, wie geht es Ihnen heute?"}]
    assert tasks._candidate_language(cues, None, job) == ("de", None)


def test_candidate_language_auto_accepts_source_lang_despite_target(monkeypatch, tmp_path):
    # The common real-world layout: English movie + Movie.en.srt, target pl,
    # source left at the default "auto". The en sidecar is exactly what the
    # translation should start from — it must NOT be rejected just because
    # en != pl. Sync + verification still gate quality.
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("en", 0.99))
    job = _gate_job(tmp_path, source_language="auto", target_language="pl")
    cues = [{"text": "Hello there, how are you doing today?"}]
    assert tasks._candidate_language(cues, None, job) == ("en", None)


def test_candidate_language_unknown_rejects(monkeypatch, tmp_path):
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: None)
    job = _gate_job(tmp_path)
    lang, reason = tasks._candidate_language([{"text": "??"}], None, job)
    assert lang is None
    assert reason


def test_gate_auto_source_accepts_en_sidecar_targeting_pl(monkeypatch, tmp_path):
    # Gate-level reproducer of the same bug: with source auto the gate must
    # use the verified en sidecar instead of falling through to ASR.
    (tmp_path / "Movie.mkv").touch()
    (tmp_path / "Movie.en.srt").write_text(_SRT)
    job = _gate_job(tmp_path)  # source auto, target pl
    monkeypatch.setattr(tasks, "_probe_duration", lambda p: None)
    monkeypatch.setattr(tasks, "_existing_subs_verdict", lambda c, d, r: "pass")
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("en", 0.99))
    monkeypatch.setattr(tasks, "_write_log", MagicMock())

    out = tasks._try_existing_subs(job, "j1", "log", None)
    assert out is not None
    assert out["language"] == "en"


def test_gate_logs_language_rejection(monkeypatch, tmp_path):
    # A candidate skipped on language must say so in the job log (verification
    # rejections already do) — and must be rejected BEFORE the expensive
    # verification battery runs.
    (tmp_path / "Movie.mkv").touch()
    (tmp_path / "Movie.srt").write_text(_SRT)
    job = _gate_job(tmp_path, source_language="fr", target_language="pl")
    log = MagicMock()
    monkeypatch.setattr(tasks, "_write_log", log)
    monkeypatch.setattr(tasks, "_probe_duration", lambda p: None)
    monkeypatch.setattr("app.worker.langid.detect_language", lambda t, **k: ("en", 0.99))
    verdict = MagicMock()
    monkeypatch.setattr(tasks, "_existing_subs_verdict", verdict)

    assert tasks._try_existing_subs(job, "j1", "log", None) is None
    verdict.assert_not_called()
    messages = " | ".join(str(c.args[3]) for c in log.call_args_list)
    assert "skipped" in messages
    assert "en" in messages


# ---------------------------------------------------------------------------
# Same-language short-circuit
# ---------------------------------------------------------------------------

def test_langs_equal_normalizes():
    assert tasks._langs_equal("eng", "en")
    assert tasks._langs_equal("pl", "pol")
    assert not tasks._langs_equal("en", "pl")
    assert not tasks._langs_equal(None, "pl")
    assert not tasks._langs_equal(None, None)


# ---------------------------------------------------------------------------
# _obtain_transcription integration: gate accept skips ASR
# ---------------------------------------------------------------------------

def test_obtain_transcription_uses_gate_result(monkeypatch, tmp_path):
    job = _gate_job(tmp_path)
    existing = {"language": "en", "existing_cues": [{"start": 1, "end": 2, "text": "Hi"}],
                "origin_path": None}
    monkeypatch.setattr(tasks, "_load_transcription_checkpoint", lambda j: None)
    monkeypatch.setattr(tasks, "_extract_audio", AsyncMock())
    monkeypatch.setattr(tasks, "_check_cancel_after", AsyncMock(return_value=None))
    monkeypatch.setattr(tasks, "_run_vad", AsyncMock(return_value=[(0.5, 2.0)]))
    monkeypatch.setattr(tasks, "_try_existing_subs", lambda *a, **kw: existing)
    monkeypatch.setattr(tasks, "_update_job", AsyncMock(return_value=job))
    saved = {}
    monkeypatch.setattr(tasks, "_save_transcription_checkpoint",
                        lambda job_id, t: saved.update(t))

    async def no_asr(*a, **kw):
        raise AssertionError("ASR must not run when the gate accepts")
    monkeypatch.setattr(tasks, "_transcribe", no_asr)

    out, cancelled = asyncio.run(
        tasks._obtain_transcription(job, "j1", "/tmp/x.wav", "log", None))
    assert cancelled is None
    assert out is existing
    assert saved["language"] == "en"  # checkpointed for resume