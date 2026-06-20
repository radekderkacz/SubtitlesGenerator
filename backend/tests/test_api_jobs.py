import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import get_db
from app.main import app
from app.models.orm import Job


def _get_db_override(row, *, for_create=False):
    async def _override():
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=row)
        mock_session.execute = AsyncMock(return_value=mock_result)
        if for_create:
            mock_session.add = MagicMock()
            mock_session.commit = AsyncMock()
            mock_session.refresh = AsyncMock()
        yield mock_session
    return _override


async def _empty_db():
    yield AsyncMock()


def _make_job(**kwargs):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        status="queued",
        phase=None,
        progress=0,
        file_path="/mnt/nas/test.mkv",
        source_language=None,
        target_language="en",
        model_size=None,
        translation_provider=None,
        translation_model=None,
        log_path=None,
        error_message=None,
        source="manual",
        created_at=now,
        updated_at=now,
        completed_at=None,
    )
    defaults.update(kwargs)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — NOT_CONFIGURED guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_jobs_not_configured_when_transcription_url_is_empty(client, make_settings_row):
    """Media path set but no transcription_api_url → 422 NOT_CONFIGURED.
    Slim refactor: 'configured' means library path + a reachable Whisper endpoint."""
    row = make_settings_row(nas_mount_path="/media", transcription_api_url=None)
    app.dependency_overrides[get_db] = _get_db_override(row)
    response = await client.post("/api/v1/jobs", json={"file_path": "/mnt/nas/test.mkv", "profile_name": "default"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "NOT_CONFIGURED"
    assert "not configured" in body["detail"].lower()


@pytest.mark.asyncio
async def test_post_jobs_not_configured_when_transcription_url_missing(client, make_settings_row):
    """Real media path but no transcription_api_url → 422 NOT_CONFIGURED."""
    row = make_settings_row(nas_mount_path="/mnt/nas", transcription_api_url=None)
    app.dependency_overrides[get_db] = _get_db_override(row)
    response = await client.post("/api/v1/jobs", json={"file_path": "/mnt/nas/test.mkv", "profile_name": "default"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_post_jobs_not_configured_when_nas_is_null(client, make_settings_row):
    """Null NAS path with backend set → 422 NOT_CONFIGURED."""
    row = make_settings_row(nas_mount_path=None, transcription_backend="remote-api")
    app.dependency_overrides[get_db] = _get_db_override(row)
    response = await client.post("/api/v1/jobs", json={"file_path": "/mnt/nas/test.mkv", "profile_name": "default"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_post_jobs_not_configured_when_settings_absent(client):
    """Missing settings row (no DB row at all) → 422 NOT_CONFIGURED, not 500."""
    app.dependency_overrides[get_db] = _get_db_override(None)
    response = await client.post("/api/v1/jobs", json={"file_path": "/mnt/nas/test.mkv", "profile_name": "default"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "NOT_CONFIGURED"


_DEFAULT_PROFILE = {"name": "default", "transcription_backend": "local-whisperx"}


@pytest.mark.asyncio
async def test_post_jobs_passes_guard_when_configured(client, make_settings_row):
    """Configured settings pass the NOT_CONFIGURED guard — returns 202 with job ID."""
    row = make_settings_row(
        nas_mount_path="/mnt/nas",
        transcription_backend="remote-api",
        profiles=[_DEFAULT_PROFILE],
    )
    app.dependency_overrides[get_db] = _get_db_override(row, for_create=True)
    with patch("app.worker.tasks.generate_subtitles") as mock_task:
        mock_task.delay.return_value = MagicMock()
        response = await client.post(
            "/api/v1/jobs",
            json={"file_path": "/mnt/nas/movies/Film.mkv", "profile_name": "default"},
        )
    assert response.status_code == 202


# ---------------------------------------------------------------------------
# POST /api/v1/jobs — full success and error cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_jobs_creates_job_and_enqueues_task(client, make_settings_row):
    """Configured + valid path + known profile → 202 with id/status/created_at, Celery enqueued."""
    row = make_settings_row(
        nas_mount_path="/mnt/nas",
        transcription_backend="remote-api",
        profiles=[_DEFAULT_PROFILE],
    )
    app.dependency_overrides[get_db] = _get_db_override(row, for_create=True)
    with patch("app.worker.tasks.generate_subtitles") as mock_task:
        mock_task.delay.return_value = MagicMock()
        response = await client.post(
            "/api/v1/jobs",
            json={"file_path": "/mnt/nas/movies/Film.mkv", "profile_name": "default", "translate": False},
        )
    assert response.status_code == 202
    body = response.json()
    assert "id" in body
    assert body["status"] == "queued"
    assert "created_at" in body
    mock_task.delay.assert_called_once_with(body["id"])


@pytest.mark.asyncio
async def test_post_jobs_publishes_creation_event_for_live_queue(client, make_settings_row):
    """A newly-created job must publish a job_update so an already-open queue
    (the SSE stream is persistent at the app-shell, never refetched on nav)
    shows it immediately — even when the worker is busy with another job.

    Regression: submitting a 2nd movie while the 1st was processing left the
    2nd invisible until the 1st finished, because creation emitted no event."""
    row = make_settings_row(
        nas_mount_path="/mnt/nas",
        transcription_backend="remote-api",
        profiles=[_DEFAULT_PROFILE],
    )
    app.dependency_overrides[get_db] = _get_db_override(row, for_create=True)
    with patch("app.worker.tasks.generate_subtitles") as mock_task, \
         patch("app.api.jobs.publish_job_update", new_callable=AsyncMock) as mock_publish:
        mock_task.delay.return_value = MagicMock()
        response = await client.post(
            "/api/v1/jobs",
            json={"file_path": "/mnt/nas/movies/Film.mkv", "profile_name": "default", "translate": False},
        )
    assert response.status_code == 202
    mock_publish.assert_awaited_once()
    published = mock_publish.await_args.args[0]
    assert published.id == response.json()["id"]
    assert published.status == "queued"


@pytest.mark.asyncio
async def test_post_jobs_rejects_auto_target_with_translate_true(client, make_settings_row):
    """Defense-in-depth backend guard: even if a stale frontend bypasses
    the UI gate, the API rejects translate=true + target_language absent/auto
    with the same 422 ValidationError shape FastAPI produces for any
    schema-level constraint failure. The body's `msg` names what to do so the
    toast on the client is actionable."""
    row = make_settings_row(nas_mount_path="/mnt/nas", transcription_backend="remote-api")
    app.dependency_overrides[get_db] = _get_db_override(row, for_create=True)
    with patch("app.worker.tasks.generate_subtitles") as mock_task:
        mock_task.delay.return_value = MagicMock()
        response = await client.post(
            "/api/v1/jobs",
            json={
                "file_path": "/mnt/nas/movies/Film.mkv",
                "profile_name": "default",
                "source_language": "auto",
                "translate": True,
                # target_language intentionally omitted → pydantic validator fires
            },
        )
    assert response.status_code == 422
    body = response.json()
    # FastAPI shapes pydantic validation errors as detail=[ {msg, ...}, ... ].
    messages = " ".join(str(item.get("msg", "")) for item in body.get("detail", []))
    assert "specific target language" in messages.lower()
    # And critically, no Celery task got dispatched.
    mock_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_post_jobs_returns_path_traversal_for_outside_path(client, make_settings_row):
    """file_path outside NAS mount root → 400 PATH_TRAVERSAL."""
    row = make_settings_row(nas_mount_path="/mnt/nas", transcription_backend="remote-api")
    app.dependency_overrides[get_db] = _get_db_override(row)
    response = await client.post(
        "/api/v1/jobs",
        json={"file_path": "/etc/passwd", "profile_name": "default"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "PATH_TRAVERSAL"
    assert body["detail"] == "Path is outside NAS mount root"


@pytest.mark.asyncio
async def test_create_job_unknown_profile_returns_422(client, make_settings_row, monkeypatch):
    """enqueue_job raising ProfileNotFoundError → 422 PROFILE_NOT_FOUND."""
    import app.api.jobs as jobs_mod

    async def boom(session, payload):
        from app.services.job_service import ProfileNotFoundError
        raise ProfileNotFoundError("ghost")

    monkeypatch.setattr(jobs_mod.job_service, "enqueue_job", boom)
    # Configure the system so the NOT_CONFIGURED guard passes and we reach enqueue.
    row = make_settings_row(nas_mount_path="/mnt/nas", transcription_backend="remote-api")
    app.dependency_overrides[get_db] = _get_db_override(row)
    resp = await client.post("/api/v1/jobs", json={"file_path": "/mnt/nas/x.mkv", "profile_name": "ghost"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "PROFILE_NOT_FOUND"
    # Pin the actionable message so it can't silently regress to e.g.
    # "AI profile '('ghost',)' not found" if the error's raised differently.
    assert "ghost" in body["detail"]
    assert "Settings → Profiles" in body["detail"]


# ---------------------------------------------------------------------------
# GET /api/v1/jobs — list
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_jobs_returns_empty_list(client):
    """No jobs in DB → 200 with empty array."""
    app.dependency_overrides[get_db] = _empty_db

    with patch("app.api.jobs.job_service.list_jobs", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = []
        response = await client.get("/api/v1/jobs")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_jobs_returns_jobs_ordered_by_created_at(client):
    """Jobs exist → 200 with list of job objects."""
    app.dependency_overrides[get_db] = _empty_db

    job1 = _make_job(file_path="/mnt/nas/film1.mkv")
    job2 = _make_job(file_path="/mnt/nas/film2.mkv")

    with patch("app.api.jobs.job_service.list_jobs", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [job1, job2]
        response = await client.get("/api/v1/jobs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert body[0]["file_path"] == "/mnt/nas/film1.mkv"
    assert body[1]["file_path"] == "/mnt/nas/film2.mkv"


# ---------------------------------------------------------------------------
# GET /api/v1/jobs/{id}
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_job_returns_job_when_found(client):
    """Job exists → 200 with full job object."""
    app.dependency_overrides[get_db] = _empty_db

    job = _make_job()

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.get(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job.id
    assert body["status"] == "queued"
    assert body["source"] == "manual"


@pytest.mark.asyncio
async def test_get_job_returns_404_when_not_found(client):
    """Job not found → 404 JOB_NOT_FOUND."""
    app.dependency_overrides[get_db] = _empty_db

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = await client.get("/api/v1/jobs/nonexistent-id")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "JOB_NOT_FOUND"
    assert "not found" in body["detail"].lower()


# ---------------------------------------------------------------------------
# DELETE /api/v1/jobs/{id} — cancel running, hard-delete queued/terminal
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_job_returns_404_when_not_found(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = await client.delete("/api/v1/jobs/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_job_cancels_processing_and_publishes_event(client):
    """Processing job → mark cancelled, publish job_update, return 200 + JobResponse."""
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(status="processing", phase="transcribing", progress=42)
    cancelled = _make_job(id=job.id, status="cancelled", phase="transcribing", progress=42)

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.api.jobs.job_service.cancel_job", new_callable=AsyncMock) as mock_cancel, \
         patch("app.api.jobs.publish_job_update", new_callable=AsyncMock) as mock_publish:
        mock_get.return_value = job
        mock_cancel.return_value = cancelled
        response = await client.delete(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == job.id
    assert body["status"] == "cancelled"
    mock_cancel.assert_awaited_once()
    mock_publish.assert_awaited_once_with(cancelled)


@pytest.mark.asyncio
async def test_delete_job_hard_removes_queued(client):
    """Queued job → hard-delete, return 204, no event published."""
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(status="queued")

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.api.jobs.job_service.delete_job", new_callable=AsyncMock) as mock_delete, \
         patch("app.api.jobs.publish_job_update", new_callable=AsyncMock) as mock_publish:
        mock_get.return_value = job
        mock_delete.return_value = True
        response = await client.delete(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 204
    assert response.content == b""
    mock_delete.assert_awaited_once()
    mock_publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_job_hard_removes_completed(client):
    """Terminal completed job → hard-delete, 204."""
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(status="completed", progress=100)

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.api.jobs.job_service.delete_job", new_callable=AsyncMock) as mock_delete:
        mock_get.return_value = job
        mock_delete.return_value = True
        response = await client.delete(f"/api/v1/jobs/{job.id}")

    assert response.status_code == 204
    mock_delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_job_hard_removes_failed_and_cancelled(client):
    app.dependency_overrides[get_db] = _empty_db
    for status in ("failed", "cancelled"):
        job = _make_job(status=status)
        with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
             patch("app.api.jobs.job_service.delete_job", new_callable=AsyncMock) as mock_delete:
            mock_get.return_value = job
            mock_delete.return_value = True
            response = await client.delete(f"/api/v1/jobs/{job.id}")
        assert response.status_code == 204, f"failed for status={status}"


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/stop-all — cancel all queued+processing
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_all_returns_empty_when_no_active_jobs(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.cancel_all_active", new_callable=AsyncMock) as mock_cancel, \
         patch("app.api.jobs.publish_job_updates", new_callable=AsyncMock) as mock_publish:
        mock_cancel.return_value = []
        response = await client.post("/api/v1/jobs/stop-all")
    assert response.status_code == 200
    assert response.json() == []
    mock_publish.assert_awaited_once_with([])


@pytest.mark.asyncio
async def test_stop_all_cancels_all_active_jobs_and_publishes_per_job(client):
    """Stop-all on N active jobs → returns list of N cancelled, fan-out publish."""
    app.dependency_overrides[get_db] = _empty_db
    cancelled = [
        _make_job(file_path="/mnt/nas/a.mkv", status="cancelled"),
        _make_job(file_path="/mnt/nas/b.mkv", status="cancelled"),
        _make_job(file_path="/mnt/nas/c.mkv", status="cancelled"),
    ]

    with patch("app.api.jobs.job_service.cancel_all_active", new_callable=AsyncMock) as mock_cancel, \
         patch("app.api.jobs.publish_job_updates", new_callable=AsyncMock) as mock_publish:
        mock_cancel.return_value = cancelled
        response = await client.post("/api/v1/jobs/stop-all")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert all(j["status"] == "cancelled" for j in body)
    mock_publish.assert_awaited_once_with(cancelled)


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{id}/retry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retry_job_404_when_source_not_found(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.retry_failed_job", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = __import__("app.services.job_service", fromlist=["RetryError"]).RetryError(
            "JOB_NOT_FOUND", "Job not found"
        )
        response = await client.post("/api/v1/jobs/missing-id/retry")
    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_retry_job_400_when_source_is_not_failed(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.retry_failed_job", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = __import__("app.services.job_service", fromlist=["RetryError"]).RetryError(
            "JOB_NOT_FAILED", "Only failed jobs can be retried (got status=processing)"
        )
        response = await client.post("/api/v1/jobs/some-id/retry")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "JOB_NOT_FAILED"
    assert "Only failed jobs" in body["detail"]


@pytest.mark.asyncio
async def test_retry_job_400_when_queued_too_fresh(client):
    """A queued job that's still fresh (< STUCK_QUEUED_THRESHOLD_SECONDS) is
    rejected with the distinct ``JOB_QUEUED_TOO_FRESH`` code so the UI can
    show a 'just wait a few more seconds' state instead of treating it
    as a permanent failure."""
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.retry_failed_job", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = __import__("app.services.job_service", fromlist=["RetryError"]).RetryError(
            "JOB_QUEUED_TOO_FRESH",
            "Job is queued but only 7s old — wait at least 30s before retrying",
        )
        response = await client.post("/api/v1/jobs/fresh-id/retry")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "JOB_QUEUED_TOO_FRESH"
    assert "wait" in body["detail"].lower()


@pytest.mark.asyncio
async def test_retry_job_happy_path(client):
    """Failed source → new queued job using current Settings; 202 + JobSubmitResponse; Celery task dispatched."""
    app.dependency_overrides[get_db] = _empty_db
    new_job = _make_job(file_path="/mnt/nas/film.mkv", status="queued")

    # Retry calls generate_subtitles.delay() directly via the api.jobs module
    # import (NOT via enqueue_job), so patch at the api.jobs symbol.
    with patch("app.api.jobs.job_service.retry_failed_job", new_callable=AsyncMock) as mock_retry, \
         patch("app.api.jobs.generate_subtitles") as mock_celery, \
         patch("app.api.jobs.publish_job_update", new_callable=AsyncMock) as mock_publish:
        mock_retry.return_value = new_job
        # Body is ignored — retry always uses current Settings.
        response = await client.post("/api/v1/jobs/source-id/retry")

    assert response.status_code == 202
    body = response.json()
    assert body["id"] == new_job.id
    assert body["status"] == "queued"
    mock_retry.assert_awaited_once()
    # service is called with just (session, source_id) — no model override.
    assert mock_retry.await_args.args[1] == "source-id"
    assert mock_retry.await_args.kwargs == {}
    mock_celery.delay.assert_called_once_with(new_job.id)
    # the re-queued job must also be published so it shows up live (same gap)
    mock_publish.assert_awaited_once()
    assert mock_publish.await_args.args[0].id == new_job.id


@pytest.mark.asyncio
async def test_retry_job_422_when_settings_not_configured(client):
    """SETTINGS_NOT_CONFIGURED → 422 with the right code."""
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.retry_failed_job", new_callable=AsyncMock) as mock_retry:
        mock_retry.side_effect = __import__("app.services.job_service", fromlist=["RetryError"]).RetryError(
            "SETTINGS_NOT_CONFIGURED", "Settings are not configured — cannot determine which model to use"
        )
        response = await client.post("/api/v1/jobs/source-id/retry")
    assert response.status_code == 422
    assert response.json()["code"] == "SETTINGS_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{id}/jellyfin-refresh
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jellyfin_refresh_404_when_job_missing(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = await client.post("/api/v1/jobs/missing/jellyfin-refresh")
    assert response.status_code == 404
    assert response.json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_jellyfin_refresh_409_when_job_not_completed(client):
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(status="processing")
    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.post(f"/api/v1/jobs/{job.id}/jellyfin-refresh")
    assert response.status_code == 409
    assert response.json()["code"] == "JOB_NOT_COMPLETED"


@pytest.mark.asyncio
async def test_jellyfin_refresh_422_when_not_configured(client, make_settings_row):
    """Settings exist but Jellyfin URL/key empty → 422 JELLYFIN_NOT_CONFIGURED."""
    job = _make_job(status="completed")
    settings = make_settings_row(jellyfin_url=None, jellyfin_api_key=None)
    app.dependency_overrides[get_db] = _get_db_override(settings)

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.post(f"/api/v1/jobs/{job.id}/jellyfin-refresh")

    assert response.status_code == 422
    assert response.json()["code"] == "JELLYFIN_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_jellyfin_refresh_502_when_jellyfin_errors(client, make_settings_row):
    from app.services.jellyfin import JellyfinRefreshError

    job = _make_job(status="completed")
    settings = make_settings_row(
        jellyfin_url="http://jf.local", jellyfin_api_key="secret"
    )
    app.dependency_overrides[get_db] = _get_db_override(settings)

    async def fake_scan(_s, **_kw):
        raise JellyfinRefreshError("Jellyfin returned HTTP 503")

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.services.jellyfin.trigger_library_scan", fake_scan):
        mock_get.return_value = job
        response = await client.post(f"/api/v1/jobs/{job.id}/jellyfin-refresh")

    assert response.status_code == 502
    assert response.json()["code"] == "JELLYFIN_REFRESH_FAILED"


@pytest.mark.asyncio
async def test_jellyfin_refresh_happy_path(client, make_settings_row):
    """Configured + scan ok → 200 with stamped jellyfin_refreshed_at + event published."""
    job = _make_job(status="completed", jellyfin_refreshed_at=None)
    settings = make_settings_row(
        jellyfin_url="http://jf.local", jellyfin_api_key="secret"
    )

    async def _override():
        # Reuse the dependency injection pattern but track commit/refresh as well.
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none = MagicMock(return_value=settings)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.get = AsyncMock(return_value=settings)
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()
        yield mock_session

    app.dependency_overrides[get_db] = _override

    async def fake_scan(_s, **_kw):
        return None

    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.services.jellyfin.trigger_library_scan", fake_scan), \
         patch("app.api.jobs.publish_job_update", new_callable=AsyncMock) as mock_publish:
        mock_get.return_value = job
        response = await client.post(f"/api/v1/jobs/{job.id}/jellyfin-refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["jellyfin_refreshed_at"] is not None
    mock_publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /api/v1/jobs/{id}/verify — Task 8
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reverify_dispatches_task(client):
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(file_path="/mnt/nas/film.mkv", status="completed")
    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get, \
         patch("app.api.jobs.verify_subtitles") as mock_task:
        mock_get.return_value = job
        response = await client.post(f"/api/v1/jobs/{job.id}/verify")
    assert response.status_code == 202
    mock_task.delay.assert_called_once_with(job.id)


@pytest.mark.asyncio
async def test_reverify_404_when_job_missing(client):
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.jobs.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = await client.post("/api/v1/jobs/nope/verify")
    assert response.status_code == 404
