"""Coverage backfill for app.services.job_service.

Direct service-layer tests using AsyncMock sessions — the API tests in
test_api_jobs.py exercise the same service indirectly, but the
service-layer branches (RetryError + cancel_all_active no-op + delete
not-found) deserve their own coverage.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.orm import Job
from app.models.schemas import JobCreate, JobStatus
from app.services import job_service


def _make_job(**overrides) -> Job:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        status="failed",
        phase="transcribing",
        progress=42,
        file_path="/media/Foo.mkv",
        source_language=None,
        target_language="en",
        model_size="large-v3",
        translation_provider=None,
        translation_model=None,
        log_path=None,
        error_message="CUDA OOM",
        source="manual",
        created_at=now,
        updated_at=now,
        completed_at=None,
        jellyfin_refreshed_at=None,
    )
    defaults.update(overrides)
    return Job(**defaults)


def _session_with_get(returned: Job | None) -> AsyncMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=returned)
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


# ---------------------------------------------------------------------------
# enqueue_job — translate=False drops target_language (rewritten for SP-2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_drops_target_language_when_translate_false(mock_session_factory):
    """translate=False must set job.target_language=None even if a target
    was somehow present in the payload.  The profile snapshot is still
    stored; the worker ignores translation fields when translate=False."""
    settings = MagicMock()
    settings.profiles = [{"name": "local"}]
    session, _ = mock_session_factory(settings=settings)
    payload = JobCreate(
        file_path="/x.mkv",
        profile_name="local",
        source_language="en",
        translate=False,
    )
    # dispatch=False — this test exercises only the row insert; the
    # Celery dispatch path is covered by test_enqueue_dispatches_*.
    job = await job_service.enqueue_job(session, payload, dispatch=False)
    assert job.target_language is None
    assert job.status == JobStatus.queued


# ---------------------------------------------------------------------------
# get_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_delegates_to_session_get():
    expected = _make_job(id="abc")
    session = _session_with_get(expected)
    found = await job_service.get_job(session, "abc")
    assert found is expected
    session.get.assert_awaited_once()


# ---------------------------------------------------------------------------
# cancel_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_job_marks_status_and_commits():
    job = _make_job(status="processing")
    session = _session_with_get(job)
    cancelled = await job_service.cancel_job(session, job.id)
    assert cancelled.status == JobStatus.cancelled
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_job_asserts_when_row_missing():
    session = _session_with_get(None)
    with pytest.raises(AssertionError):
        await job_service.cancel_job(session, "missing")


# ---------------------------------------------------------------------------
# delete_job
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_job_returns_true_when_row_existed():
    job = _make_job(status="completed")
    session = _session_with_get(job)
    assert await job_service.delete_job(session, job.id) is True
    session.delete.assert_awaited_once_with(job)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_job_returns_false_when_missing():
    session = _session_with_get(None)
    assert await job_service.delete_job(session, "x") is False
    session.delete.assert_not_called()


# ---------------------------------------------------------------------------
# retry_failed_job
# ---------------------------------------------------------------------------

def _session_with_job_and_settings(job, settings) -> AsyncMock:
    """Session.get(Job, …) returns job; .get(Settings, 1) returns settings."""
    from app.models.orm import Job as JobCls, Settings as SettingsCls
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    async def _get(cls, _id):
        if cls is JobCls:
            return job
        if cls is SettingsCls:
            return settings
        return None
    session.get = AsyncMock(side_effect=_get)
    return session


def _make_settings(**overrides) -> MagicMock:
    s = MagicMock()
    s.translation_provider = "ollama"
    s.translation_model = "gpt-oss:20b"
    s.translation_api_url = "http://localhost:11434"
    s.translation_api_key = None
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_retry_failed_job_raises_not_found_when_source_missing():
    session = _session_with_job_and_settings(None, _make_settings())
    with pytest.raises(job_service.RetryError) as exc:
        await job_service.retry_failed_job(session, "nope")
    assert exc.value.code == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_retry_failed_job_raises_when_source_not_failed():
    job = _make_job(status="completed")
    session = _session_with_job_and_settings(job, _make_settings())
    with pytest.raises(job_service.RetryError) as exc:
        await job_service.retry_failed_job(session, job.id)
    assert exc.value.code == "JOB_NOT_FAILED"


@pytest.mark.asyncio
async def test_retry_failed_job_accepts_queued_job_when_older_than_stuck_threshold():
    """A job inserted into the DB but never picked up by Celery (the orphan-
    queued bug from 2026-05-15) must be recoverable through the same retry
    path. The threshold prevents accidental retries on a freshly submitted
    job that just hasn't been picked up YET.
    """
    from datetime import timedelta
    stuck_since = datetime.now(timezone.utc) - timedelta(
        seconds=job_service.STUCK_QUEUED_THRESHOLD_SECONDS + 5
    )
    source = _make_job(
        status="queued",
        updated_at=stuck_since,
        target_language="pl",
        file_path="/media/orphan.mkv",
    )
    settings = _make_settings()
    session = _session_with_job_and_settings(source, settings)

    new_job = await job_service.retry_failed_job(session, source.id)

    assert new_job is not source
    assert new_job.status == JobStatus.queued
    # Same file + target language — this IS a recovery of the orphan, not a new job
    assert new_job.file_path == source.file_path
    assert new_job.target_language == source.target_language
    session.add.assert_called_once_with(new_job)


@pytest.mark.asyncio
async def test_retry_failed_job_rejects_queued_job_younger_than_stuck_threshold():
    """A job that's only been queued for a few seconds is probably just
    waiting for the worker to pick it up — surfacing a "retry" UI for it
    would invite the user to double-submit. Reject with a distinct code so
    the frontend can show a 'wait N seconds' message instead of treating it
    like a hard error.
    """
    from datetime import timedelta
    fresh = datetime.now(timezone.utc) - timedelta(seconds=2)
    job = _make_job(status="queued", updated_at=fresh)
    session = _session_with_job_and_settings(job, _make_settings())

    with pytest.raises(job_service.RetryError) as exc:
        await job_service.retry_failed_job(session, job.id)
    assert exc.value.code == "JOB_QUEUED_TOO_FRESH"
    # Message names the threshold so users can copy-paste timing into a bug
    # report if needed.
    assert str(job_service.STUCK_QUEUED_THRESHOLD_SECONDS) in str(exc.value)
    # No new row was added — important so a misclick on a still-good job
    # doesn't pollute history.
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_retry_failed_job_rejects_processing_and_completed_and_cancelled():
    """Only failed + stale-queued are retryable. Everything else (processing,
    completed, cancelled) keeps the legacy JOB_NOT_FAILED rejection so
    callers built against the old contract still recognise the response."""
    for status in ("processing", "completed", "cancelled"):
        job = _make_job(status=status)
        session = _session_with_job_and_settings(job, _make_settings())
        with pytest.raises(job_service.RetryError) as exc:
            await job_service.retry_failed_job(session, job.id)
        assert exc.value.code == "JOB_NOT_FAILED", f"status={status} should keep legacy code"


@pytest.mark.asyncio
async def test_retry_failed_job_carries_snapshot_from_original():
    """Retry copies backend_profile from the original job so the retried run
    is identical to the original attempt.  Legacy model_size / translation_*
    columns are left unset (None) on the new job — they are no longer the
    config source after SP-2."""
    snap = {
        "name": "groq-gemini",
        "transcription_backend": "remote-api",
        "translation_model": "google/gemini-2.0-flash-001",
    }
    source = _make_job(
        status="failed",
        model_size="large-v2",
        translation_provider="ollama",
        translation_model="qwen3.6:35b",
        target_language="pl",
        backend_profile=snap,
    )
    session = _session_with_job_and_settings(source, _make_settings())

    new_job = await job_service.retry_failed_job(session, source.id)

    assert new_job is not source
    assert new_job.status == JobStatus.queued
    # Snapshot copied verbatim
    assert new_job.backend_profile == snap
    # Per-job intent (file + languages) preserved
    assert new_job.target_language == "pl"
    assert new_job.file_path == source.file_path
    # Legacy columns must NOT be populated — they are no longer the config source
    assert new_job.model_size is None
    assert new_job.translation_provider is None
    assert new_job.translation_model is None
    session.add.assert_called_once_with(new_job)


@pytest.mark.asyncio
async def test_retry_failed_job_preserves_no_translation_when_target_language_is_none():
    """If the original job had no target_language (transcribe-only), the retry
    also has target_language=None — no translation will occur."""
    snap = {"name": "local", "transcription_backend": "remote-api"}
    source = _make_job(
        status="failed",
        target_language=None,
        backend_profile=snap,
    )
    session = _session_with_job_and_settings(source, _make_settings())

    new_job = await job_service.retry_failed_job(session, source.id)

    assert new_job.target_language is None
    assert new_job.backend_profile == snap


# ---------------------------------------------------------------------------
# cancel_all_active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cancel_all_active_returns_empty_when_no_active_rows():
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    cancelled = await job_service.cancel_all_active(session)
    assert cancelled == []
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_all_active_marks_each_active_row_cancelled():
    j1 = _make_job(status="processing")
    j2 = _make_job(status="queued")
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [j1, j2]
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()

    cancelled = await job_service.cancel_all_active(session)
    assert {c.status for c in cancelled} == {JobStatus.cancelled}
    session.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# RetryError
# ---------------------------------------------------------------------------

def test_retry_error_carries_code_and_message():
    err = job_service.RetryError("CODE_X", "human-readable message")
    assert err.code == "CODE_X"
    assert str(err) == "human-readable message"


# ---------------------------------------------------------------------------
# enqueue_job — profile-snapshot behaviour (SP-2 Task 3)
# ---------------------------------------------------------------------------

def _settings(profiles):
    s = MagicMock()
    s.profiles = profiles
    return s


@pytest.mark.asyncio
async def test_enqueue_snapshots_named_profile(mock_session_factory):
    prof = {
        "name": "groq-gemini",
        "transcription_backend": "remote-api",
        "transcription_api_url": "https://api.groq.com/openai/v1",
        "transcription_model": "whisper-large-v3-turbo",
        "transcription_api_key": "gk",
        "translation_provider": "openrouter",
        "translation_model": "google/gemini-2.0-flash-001",
        "translation_api_url": None,
        "translation_api_key": "or-k",
    }
    session, added = mock_session_factory(settings=_settings([prof]))
    payload = JobCreate(
        file_path="/m/x.mkv",
        profile_name="groq-gemini",
        source_language="auto",
        translate=True,
        target_language="pl",
    )
    # dispatch=False — this test asserts the row-snapshot, not Celery side effects.
    job = await job_service.enqueue_job(session, payload, dispatch=False)
    snap = job.backend_profile
    assert snap["name"] == "groq-gemini"
    assert snap["transcription_backend"] == "remote-api"
    assert snap["transcription_api_key"] == "gk"
    assert snap["translation_model"] == "google/gemini-2.0-flash-001"
    assert snap["translation_api_key"] == "or-k"
    assert job.source_language == "auto"
    assert job.target_language == "pl"


# ─────────────────────────────────────────────────────────────────────────────
# Atomic chokepoint: enqueue_job must dispatch the Celery task itself, so
# no caller can forget step 2. Four caller-trust bugs in 2 days made this
# the architectural fix. Edge cases proactively pinned below.
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enqueue_dispatches_celery_by_default(mock_session_factory, monkeypatch):
    session, _ = mock_session_factory(
        settings=_settings([{"name": "P1", "transcription_backend": "remote-api"}])
    )
    delay_calls: list[str] = []
    monkeypatch.setattr(
        "app.worker.tasks.generate_subtitles",
        MagicMock(delay=MagicMock(side_effect=lambda jid: delay_calls.append(jid))),
    )
    job = await job_service.enqueue_job(
        session, JobCreate(file_path="/m/x.mkv", profile_name="P1")
    )
    assert delay_calls == [job.id], "default enqueue_job must dispatch Celery"


@pytest.mark.asyncio
async def test_enqueue_dispatch_false_skips_celery(mock_session_factory, monkeypatch):
    """Opt-out for callers that need to mutate after insert."""
    session, _ = mock_session_factory(
        settings=_settings([{"name": "P1", "transcription_backend": "remote-api"}])
    )
    delay_calls: list[str] = []
    monkeypatch.setattr(
        "app.worker.tasks.generate_subtitles",
        MagicMock(delay=MagicMock(side_effect=lambda jid: delay_calls.append(jid))),
    )
    await job_service.enqueue_job(
        session, JobCreate(file_path="/m/x.mkv", profile_name="P1"), dispatch=False
    )
    assert delay_calls == []


@pytest.mark.asyncio
async def test_enqueue_does_not_dispatch_when_profile_missing(mock_session_factory, monkeypatch):
    """Defense-in-depth: a failed DB-side gate must never fire a stray task."""
    session, _ = mock_session_factory(settings=_settings([{"name": "other"}]))
    delay_calls: list[str] = []
    monkeypatch.setattr(
        "app.worker.tasks.generate_subtitles",
        MagicMock(delay=MagicMock(side_effect=lambda jid: delay_calls.append(jid))),
    )
    with pytest.raises(job_service.ProfileNotFoundError):
        await job_service.enqueue_job(
            session, JobCreate(file_path="/m/x.mkv", profile_name="missing")
        )
    assert delay_calls == [], "ProfileNotFoundError must NOT fire Celery"


@pytest.mark.asyncio
async def test_dispatch_event_triggers_celery_via_enqueue_job(monkeypatch):
    """End-to-end contract: a watch-trigger fire on a video file must result
    in a Celery .delay() call. This is the actual bug — pre-fix the trigger
    pipeline left jobs queued forever because dispatch_event called
    enqueue_job but never .delay()."""
    from app.services.trigger_executor import MatchEvent, dispatch_event

    trig = type("T", (), {
        "id": "t-watch",
        "type": "watch",
        "config": {"path": "/x"},
        "action": {"profile_name": "P1", "source_language": None,
                   "target_language": None, "skip_if_srt": True},
        "file_filter": {"type": "all", "value": None},
    })()

    delay_calls: list[str] = []
    monkeypatch.setattr(
        "app.worker.tasks.generate_subtitles",
        MagicMock(delay=MagicMock(side_effect=lambda jid: delay_calls.append(jid))),
    )

    # Real enqueue_job path; stub only the SQLAlchemy bits.
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(
        return_value=_settings([{"name": "P1", "transcription_backend": "remote-api"}])
    )
    session.execute = AsyncMock(return_value=exec_result)

    from unittest.mock import patch as _patch
    with _patch("app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)), \
         _patch("app.services.trigger_executor._profile_exists", AsyncMock(return_value=True)):
        outcome = await dispatch_event(
            session, MatchEvent("t-watch", "/x/m.mkv", {})
        )

    assert outcome == "submitted"
    assert len(delay_calls) == 1, "trigger pipeline must dispatch Celery — was forever-queued before"


@pytest.mark.asyncio
async def test_dispatch_event_does_not_dispatch_celery_for_non_video(monkeypatch):
    """Ordering proof: the video gate runs before enqueue_job, so non-video
    events never reach the Celery dispatcher."""
    from app.services.trigger_executor import MatchEvent, dispatch_event

    trig = type("T", (), {
        "id": "t-watch",
        "type": "watch",
        "config": {"path": "/x"},
        "action": {"profile_name": "P1", "source_language": None,
                   "target_language": None, "skip_if_srt": True},
        "file_filter": {"type": "all", "value": None},
    })()

    delay_calls: list[str] = []
    monkeypatch.setattr(
        "app.worker.tasks.generate_subtitles",
        MagicMock(delay=MagicMock(side_effect=lambda jid: delay_calls.append(jid))),
    )

    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    from unittest.mock import patch as _patch
    with _patch("app.services.trigger_executor._get_trigger", AsyncMock(return_value=trig)):
        outcome = await dispatch_event(
            session, MatchEvent("t-watch", "/x/poster.jpg", {})
        )
    assert outcome == "skipped_not_video"
    assert delay_calls == []


@pytest.mark.asyncio
async def test_enqueue_unknown_profile_raises(mock_session_factory):
    session, _ = mock_session_factory(settings=_settings([{"name": "other"}]))
    with pytest.raises(job_service.ProfileNotFoundError) as exc:
        await job_service.enqueue_job(
            session, JobCreate(file_path="/m/x.mkv", profile_name="missing")
        )
    # T5 maps this exception's arg into the 422 message — pin the contract.
    assert exc.value.args[0] == "missing"


@pytest.mark.asyncio
async def test_enqueue_no_profiles_raises(mock_session_factory):
    session, _ = mock_session_factory(settings=_settings([]))
    with pytest.raises(job_service.ProfileNotFoundError):
        await job_service.enqueue_job(
            session, JobCreate(file_path="/m/x.mkv", profile_name="any")
        )


@pytest.mark.asyncio
async def test_retry_carries_backend_profile_and_languages(mock_session_factory):
    from app.services.job_service import retry_failed_job
    from app.models.schemas import JobStatus
    snap = {"name": "p", "transcription_backend": "remote-api"}
    session, _ = mock_session_factory(existing_job=dict(
        id="orig", status=JobStatus.failed, file_path="/m/x.mkv",
        source_language="en", target_language="pl", backend_profile=snap))
    new = await retry_failed_job(session, "orig")
    assert new.backend_profile == snap
    assert new.source_language == "en"
    assert new.target_language == "pl"
    assert new.file_path == "/m/x.mkv"
    assert new.id != "orig"
    assert new.status == JobStatus.queued
