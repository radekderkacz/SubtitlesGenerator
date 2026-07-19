"""Auto-retry after failed verification: cost gate, lineage cap, worker hook."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.worker import tasks
from app.worker.auto_retry import (
    AUTO_RETRY_SOURCE_PREFIX,
    is_cost_free_backend,
    should_auto_retry,
)


# ---------------------------------------------------------------------------
# is_cost_free_backend — the conservative "free to re-run" heuristic
# ---------------------------------------------------------------------------

def test_free_local_stack():
    # Keyless (self-hosted) transcription + ollama translation = free.
    assert is_cost_free_backend(
        {"transcription_api_key": "", "translation_provider": "ollama"}, "pl")


def test_free_transcription_only_job():
    # No translation at all: only the keyless transcription matters.
    assert is_cost_free_backend({"transcription_api_key": None}, None)


def test_paid_transcription_key_blocks():
    # A key on the ASR endpoint means hosted (Groq/OpenAI) — never free.
    assert not is_cost_free_backend(
        {"transcription_api_key": "gsk_x", "translation_provider": "ollama"}, "pl")


@pytest.mark.parametrize("provider", ["openai", "google", "openrouter", "custom", None])
def test_paid_translation_provider_blocks(provider):
    assert not is_cost_free_backend(
        {"transcription_api_key": "", "translation_provider": provider}, "pl")


def test_non_ollama_translation_free_when_no_target():
    # Paid translation config is irrelevant if the job doesn't translate.
    assert is_cost_free_backend(
        {"transcription_api_key": "", "translation_provider": "openai"}, None)


# ---------------------------------------------------------------------------
# should_auto_retry — eligibility
# ---------------------------------------------------------------------------

def _job(**kw):
    base = dict(
        id="j1", source="manual", verification_status="fail",
        source_language="en", target_language="pl",
        file_path="/media/Film.mkv", verification_report=None,
        source_srt_path=None,
        backend_profile={"transcription_api_key": "", "translation_provider": "ollama"},
    )
    base.update(kw)
    return type("J", (), base)()


def test_eligible_fail_on_free_profile():
    assert should_auto_retry(_job())


def test_warn_and_error_do_not_retry():
    assert not should_auto_retry(_job(verification_status="warn"))
    assert not should_auto_retry(_job(verification_status="error"))
    assert not should_auto_retry(_job(verification_status="pass"))


def test_auto_regen_job_never_retries_again():
    # Lineage cap: the clone carries the prefix, so the chain stops at one.
    assert not should_auto_retry(_job(source=f"{AUTO_RETRY_SOURCE_PREFIX}orig"))


def test_paid_profile_stays_flagged():
    assert not should_auto_retry(_job(
        backend_profile={"transcription_api_key": "sk-x", "translation_provider": "ollama"}))


def test_missing_backend_profile_blocks():
    assert not should_auto_retry(_job(backend_profile=None))


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("SUBGEN_DISABLE_AUTO_RETRY", "1")
    assert not should_auto_retry(_job())


# ---------------------------------------------------------------------------
# run_verification hook — only the fresh-generation path may retry
# ---------------------------------------------------------------------------

def _wire_verification(monkeypatch, status):
    job = _job()
    monkeypatch.setattr(tasks, "_fetch_job", AsyncMock(return_value=job))

    async def fake_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job
    monkeypatch.setattr(tasks, "_update_job", fake_update)
    monkeypatch.setattr(tasks, "_publish_job_update_safe", AsyncMock())
    monkeypatch.setattr(
        tasks, "_run_verification_verdict",
        lambda j: {"status": status, "score": 0.0, "report": {"summary": "", "checks": []}})
    retry = AsyncMock()
    monkeypatch.setattr(tasks, "_maybe_auto_retry", retry)
    return retry


def test_fail_verdict_on_pipeline_path_triggers_retry(monkeypatch):
    retry = _wire_verification(monkeypatch, "fail")
    asyncio.run(tasks.run_verification("j1", allow_auto_retry=True))
    retry.assert_awaited_once()


def test_manual_reverify_never_triggers_retry(monkeypatch):
    retry = _wire_verification(monkeypatch, "fail")
    asyncio.run(tasks.run_verification("j1"))
    retry.assert_not_awaited()


def test_pass_verdict_does_not_trigger_retry(monkeypatch):
    retry = _wire_verification(monkeypatch, "pass")
    asyncio.run(tasks.run_verification("j1", allow_auto_retry=True))
    retry.assert_not_awaited()


# ---------------------------------------------------------------------------
# _maybe_auto_retry — dispatch, provenance link, failure containment
# ---------------------------------------------------------------------------

def _wire_retry(monkeypatch, tmp_path, regen=None):
    monkeypatch.setattr(tasks, "_LOG_DIR", str(tmp_path))
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: session)
    if regen is not None:
        monkeypatch.setattr("app.services.job_service.regenerate_job", regen)
    delay = MagicMock()
    monkeypatch.setattr(tasks.generate_subtitles, "delay", delay)
    updates = {}

    async def fake_update(job_id, **fields):
        updates.update(fields)
        return _job(**fields)
    monkeypatch.setattr(tasks, "_update_job", fake_update)
    monkeypatch.setattr(tasks, "_publish_job_update_safe", AsyncMock())
    return delay, updates


def test_retry_queues_clone_and_links_report(monkeypatch, tmp_path):
    new_job = _job(id="j2", source=f"{AUTO_RETRY_SOURCE_PREFIX}j1")
    regen = AsyncMock(return_value=new_job)
    delay, updates = _wire_retry(monkeypatch, tmp_path, regen)
    job = _job(verification_report={"summary": "broken", "checks": []})

    asyncio.run(tasks._maybe_auto_retry(job))

    regen.assert_awaited_once()
    assert regen.await_args.kwargs["source"] == f"{AUTO_RETRY_SOURCE_PREFIX}j1"
    delay.assert_called_once_with("j2")
    assert updates["verification_report"]["auto_retry_job_id"] == "j2"
    assert updates["verification_report"]["summary"] == "broken"


def test_ineligible_job_never_touches_db(monkeypatch, tmp_path):
    regen = AsyncMock()
    delay, _ = _wire_retry(monkeypatch, tmp_path, regen)
    asyncio.run(tasks._maybe_auto_retry(_job(verification_status="warn")))
    regen.assert_not_awaited()
    delay.assert_not_called()


def test_already_active_guard_skips_quietly(monkeypatch, tmp_path):
    from app.services.job_service import RegenerateError
    regen = AsyncMock(side_effect=RegenerateError("ALREADY_ACTIVE", "dup"))
    delay, updates = _wire_retry(monkeypatch, tmp_path, regen)
    asyncio.run(tasks._maybe_auto_retry(_job()))  # must not raise
    delay.assert_not_called()
    assert "verification_report" not in updates


def test_unexpected_error_is_contained(monkeypatch, tmp_path):
    regen = AsyncMock(side_effect=RuntimeError("db down"))
    delay, _ = _wire_retry(monkeypatch, tmp_path, regen)
    asyncio.run(tasks._maybe_auto_retry(_job()))  # must not raise
    delay.assert_not_called()


# ---------------------------------------------------------------------------
# Fast re-translate path: _fast_retry_srt classification
# ---------------------------------------------------------------------------

_SRT = "1\n00:00:01,000 --> 00:00:02,500\nHello there, how are you?\n"


def _report(*fails, warns=()):
    checks = [{"layer": "semantic", "name": n, "severity": "fail"} for n in fails]
    checks += [{"layer": "heuristic", "name": n, "severity": "warn"} for n in warns]
    return {"summary": "", "checks": checks}


def _media_job(tmp_path, report, **kw):
    video = tmp_path / "Film.mkv"
    (tmp_path / "Film.en.srt").write_text(_SRT)
    return _job(file_path=str(video), source_language="en",
                verification_report=report, **kw)


def test_translation_only_fails_reuse_source_srt(tmp_path):
    job = _media_job(tmp_path, _report("output_language", "alignment"))
    assert tasks._fast_retry_srt(job) == str(tmp_path / "Film.en.srt")


def test_audio_side_fail_forces_full_rerun(tmp_path):
    job = _media_job(tmp_path, _report("output_language", "av_sync"))
    assert tasks._fast_retry_srt(job) is None


def test_no_fails_means_no_fast_path(tmp_path):
    job = _media_job(tmp_path, _report(warns=("reading_speed",)))
    assert tasks._fast_retry_srt(job) is None


def test_missing_source_srt_forces_full_rerun(tmp_path):
    job = _media_job(tmp_path, _report("output_language"))
    (tmp_path / "Film.en.srt").unlink()
    assert tasks._fast_retry_srt(job) is None


def test_untranslated_job_never_fast_paths(tmp_path):
    job = _media_job(tmp_path, _report("output_language"), target_language=None)
    assert tasks._fast_retry_srt(job) is None


def test_full_rerun_clears_srt_source_and_existing_subs(monkeypatch, tmp_path):
    """An audio-side fail forces a genuine re-transcription: the clone must
    not inherit an SRT source NOR re-pick the same existing subtitle track."""
    new_job = _job(id="j2", source=f"{AUTO_RETRY_SOURCE_PREFIX}j1")
    regen = AsyncMock(return_value=new_job)
    delay, _ = _wire_retry(monkeypatch, tmp_path, regen)
    job = _media_job(tmp_path, _report("av_sync"))

    asyncio.run(tasks._maybe_auto_retry(job))

    assert regen.await_args.kwargs["source_srt_path"] is None
    assert regen.await_args.kwargs["use_existing_subs"] is False
    delay.assert_called_once_with("j2")


def test_retry_passes_fast_srt_to_clone(monkeypatch, tmp_path):
    new_job = _job(id="j2", source=f"{AUTO_RETRY_SOURCE_PREFIX}j1")
    regen = AsyncMock(return_value=new_job)
    delay, _ = _wire_retry(monkeypatch, tmp_path, regen)
    job = _media_job(tmp_path, _report("alignment"))

    asyncio.run(tasks._maybe_auto_retry(job))

    assert regen.await_args.kwargs["source_srt_path"] == str(tmp_path / "Film.en.srt")
    delay.assert_called_once_with("j2")


# ---------------------------------------------------------------------------
# SRT-as-source pipeline stage
# ---------------------------------------------------------------------------

def test_load_source_srt_cues_parses_file(tmp_path):
    srt = tmp_path / "Film.en.srt"
    srt.write_text(_SRT)
    job = _job(source_srt_path=str(srt))
    cues = tasks._load_source_srt_cues(job, str(tmp_path / "log"))
    assert cues == [{"index": 1, "start": 1.0, "end": 2.5,
                     "text": "Hello there, how are you?"}]


def test_load_source_srt_cues_missing_file_falls_back(tmp_path):
    job = _job(source_srt_path=str(tmp_path / "gone.srt"))
    assert tasks._load_source_srt_cues(job, str(tmp_path / "log")) is None


def test_load_source_srt_cues_garbage_falls_back(tmp_path):
    srt = tmp_path / "bad.srt"
    srt.write_text("not an srt at all")
    job = _job(source_srt_path=str(srt))
    assert tasks._load_source_srt_cues(job, str(tmp_path / "log")) is None


def test_load_source_srt_cues_unset_is_none(tmp_path):
    assert tasks._load_source_srt_cues(_job(source_srt_path=None), "log") is None


def test_source_cues_stage_skips_transcription(monkeypatch, tmp_path):
    srt = tmp_path / "Film.en.srt"
    srt.write_text(_SRT)
    job = _job(source_srt_path=str(srt))

    async def boom(*a, **kw):
        raise AssertionError("transcription must not run on the SRT path")
    monkeypatch.setattr(tasks, "_obtain_transcription", boom)
    monkeypatch.setattr(tasks, "_update_job", AsyncMock(return_value=job))

    out_job, cues, source_srt, cancelled = asyncio.run(
        tasks._source_cues_stage(job, "j1", "/tmp/x.wav", str(tmp_path / "log"), None))
    assert cancelled is None
    assert source_srt == str(srt)
    assert len(cues) == 1 and cues[0]["text"] == "Hello there, how are you?"


def test_source_cues_stage_falls_back_to_asr(monkeypatch, tmp_path):
    job = _job(source_srt_path=None)
    monkeypatch.setattr(tasks, "_obtain_transcription",
                        AsyncMock(return_value=(None, {"status": "cancelled"})))
    out_job, cues, source_srt, cancelled = asyncio.run(
        tasks._source_cues_stage(job, "j1", "/tmp/x.wav", str(tmp_path / "log"), None))
    assert cancelled == {"status": "cancelled"}
    assert cues is None
