"""
History API and Log API.

The five acceptance criteria from epics.md:

1. GET /api/v1/history returns completed/failed/cancelled jobs ordered DESC.
2. GET /api/v1/history?status=<terminal> filters to that status.
3. GET /api/v1/history/{id}/log returns log file as text/plain.
4. GET /api/v1/history/{id}/log returns 404 + LOG_NOT_FOUND when missing.
5. DELETE /api/v1/history purges terminal jobs only.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import ANY, AsyncMock, patch

import pytest

from app.core.database import get_db
from app.main import app
from app.models.orm import Job


async def _empty_db():
    yield AsyncMock()


def _make_job(**kwargs) -> Job:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        status="completed",
        phase=None,
        progress=100,
        file_path="/mnt/nas/test.mkv",
        source_language="en",
        target_language="en",
        model_size="large-v3",
        translation_provider=None,
        translation_model=None,
        log_path=None,
        error_message=None,
        source="manual",
        created_at=now,
        updated_at=now,
        completed_at=now,
    )
    defaults.update(kwargs)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# AC1 + AC2 — list endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_list_returns_terminal_jobs_descending_with_srt_path(client):
    """All terminal statuses, ordered desc, srt_path derived for completed."""
    app.dependency_overrides[get_db] = _empty_db
    now = datetime.now(timezone.utc)
    completed = _make_job(
        file_path="/mnt/nas/Film.mkv",
        target_language="en",
        status="completed",
        created_at=now,
        source_srt_path="/mnt/nas/Film.en.srt",
    )
    failed = _make_job(
        file_path="/mnt/nas/Other.mkv",
        target_language="fr",
        status="failed",
        error_message="CUDA OOM",
        created_at=now - timedelta(minutes=10),
    )
    cancelled = _make_job(
        file_path="/mnt/nas/Third.mkv",
        target_language="de",
        status="cancelled",
        created_at=now - timedelta(minutes=20),
    )

    with patch("app.api.history.job_service.list_history", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [completed, failed, cancelled]
        response = await client.get("/api/v1/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 3
    assert [r["status"] for r in body] == ["completed", "failed", "cancelled"]
    assert body[0]["srt_path"] == "/mnt/nas/Film.en.srt"
    # provenance: this run translated from an existing SRT; the others didn't
    assert body[0]["source_srt_path"] == "/mnt/nas/Film.en.srt"
    assert body[1]["source_srt_path"] is None
    # AC1 includes error_message
    assert body[1]["error_message"] == "CUDA OOM"
    # cancelled with target_language gets srt_path too — only the file is gone
    assert body[2]["srt_path"] == "/mnt/nas/Third.de.srt"
    # service was called with no filter
    mock_list.assert_awaited_once_with(ANY, status_filter=None)


@pytest.mark.asyncio
async def test_history_list_status_filter_passed_to_service(client):
    """?status=failed forwards a filter to the service layer."""
    app.dependency_overrides[get_db] = _empty_db
    failed = _make_job(status="failed", error_message="oops")
    with patch("app.api.history.job_service.list_history", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [failed]
        response = await client.get("/api/v1/history?status=failed")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "failed"
    # Filter delivered to the service.
    mock_list.assert_awaited_once_with(ANY, status_filter="failed")


@pytest.mark.asyncio
async def test_history_list_status_filter_invalid_returns_422(client):
    """?status=processing isn't a terminal state → 422."""
    app.dependency_overrides[get_db] = _empty_db
    response = await client.get("/api/v1/history?status=processing")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_history_list_srt_path_null_when_target_language_missing(client):
    """A terminal job that never reached the writing phase has no srt_path."""
    app.dependency_overrides[get_db] = _empty_db
    failed_early = _make_job(status="failed", target_language=None, error_message="nope")
    with patch("app.api.history.job_service.list_history", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [failed_early]
        response = await client.get("/api/v1/history")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["srt_path"] is None


# ---------------------------------------------------------------------------
# AC3 + AC4 — log endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_log_returns_text_plain_when_file_exists(client, tmp_path, monkeypatch):
    """Existing log file → 200 text/plain with full content."""
    monkeypatch.setenv("SUBGEN_LOG_DIR", str(tmp_path))
    job_id = str(uuid.uuid4())
    log_file = tmp_path / f"{job_id}.log"
    content = "2026-04-24T12:00:00Z INFO  [job:abc] Job started\n2026-04-24T12:00:01Z INFO  [job:abc] Done\n"
    log_file.write_text(content)

    job = _make_job(id=job_id, status="completed")
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.get(f"/api/v1/history/{job_id}/log")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == content


@pytest.mark.asyncio
async def test_history_log_returns_404_log_not_found_when_file_missing(client, tmp_path, monkeypatch):
    """Job exists but its log file does not → 404 with LOG_NOT_FOUND."""
    monkeypatch.setenv("SUBGEN_LOG_DIR", str(tmp_path))
    job_id = str(uuid.uuid4())
    job = _make_job(id=job_id, status="completed")
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.get(f"/api/v1/history/{job_id}/log")

    assert response.status_code == 404
    body = response.json()
    assert body == {"detail": "Log not found", "code": "LOG_NOT_FOUND"}


@pytest.mark.asyncio
async def test_history_log_returns_404_when_job_missing(client):
    """No such job → 404 with JOB_NOT_FOUND."""
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None
        response = await client.get("/api/v1/history/does-not-exist/log")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_history_log_rejects_non_uuid_job_id(client):
    """`job_id` is parsed as a UUID at the boundary; anything else 404s
    before it can flow into a filesystem path (CWE-22 sanitisation).

    httpx + FastAPI normalise dot-segment URLs like `/api/v1/history/..`
    away before the route matches, so we test with non-traversal but
    not-a-uuid strings here. The traversal payloads can't reach the
    handler regardless because the path no longer uses the URL value.
    """
    app.dependency_overrides[get_db] = _empty_db
    for bogus in ["not-a-uuid", "abc", "12345", "deadbeef"]:
        response = await client.get(f"/api/v1/history/{bogus}/log")
        assert response.status_code == 404, f"{bogus!r} got {response.status_code}"
        assert response.json()["code"] == "JOB_NOT_FOUND"


@pytest.mark.asyncio
async def test_history_log_ignores_db_log_path_for_path_construction(
    client, tmp_path, monkeypatch,
):
    """The endpoint builds the path from the validated UUID + SUBGEN_LOG_DIR
    only. A DB row that points elsewhere is irrelevant — the file lookup
    only checks the safe path."""
    monkeypatch.setenv("SUBGEN_LOG_DIR", str(tmp_path))
    job_id = str(uuid.uuid4())
    # Create the file at the SAFE path
    (tmp_path / f"{job_id}.log").write_text("real log")
    # Even if `log_path` on the row points at /etc/passwd, the endpoint
    # ignores it — only `<SUBGEN_LOG_DIR>/<uuid>.log` is read.
    job = _make_job(id=job_id, status="completed", log_path="/etc/passwd")

    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.get(f"/api/v1/history/{job_id}/log")

    assert response.status_code == 200
    assert response.text == "real log"


@pytest.mark.asyncio
async def test_history_log_falls_back_to_default_dir_when_log_path_null(client, tmp_path, monkeypatch):
    """Job without log_path on the row still works if ./data/logs/{id}.log exists."""
    job_id = str(uuid.uuid4())
    monkeypatch.setenv("SUBGEN_LOG_DIR", str(tmp_path))
    log_file = tmp_path / f"{job_id}.log"
    log_file.write_text("fallback\n")

    job = _make_job(id=job_id, status="completed", log_path=None)
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.get_job", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = job
        response = await client.get(f"/api/v1/history/{job_id}/log")

    assert response.status_code == 200
    assert response.text == "fallback\n"


# ---------------------------------------------------------------------------
# AC5 — purge endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_delete_purges_terminal_jobs(client):
    """DELETE /api/v1/history removes terminal rows; preserves active+queued."""
    app.dependency_overrides[get_db] = _empty_db
    with patch("app.api.history.job_service.delete_terminal_jobs", new_callable=AsyncMock) as mock_del:
        mock_del.return_value = 7
        response = await client.delete("/api/v1/history")

    assert response.status_code == 200
    assert response.json() == {"deleted": 7}
    mock_del.assert_awaited_once()


# ---------------------------------------------------------------------------
# Service layer — SQL filter verification
#
# The API tests above mock the service layer, so the actual WHERE clauses are
# never exercised. These tests inspect the compiled SQL to confirm that the
# service functions filter to terminal statuses only — the contract
# AC5 hinges on (DELETE preserves queued/processing rows).
# ---------------------------------------------------------------------------

from unittest.mock import MagicMock  # noqa: E402

from app.services import job_service  # noqa: E402


def _compiled_sql(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True})).lower()


def _mock_session_capturing_execute() -> tuple[AsyncMock, list]:
    captured: list = []
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_result.rowcount = 0

    async def _execute(stmt, *args, **kwargs):
        captured.append(stmt)
        return mock_result

    session.execute = _execute
    session.commit = AsyncMock()
    return session, captured


@pytest.mark.asyncio
async def test_list_history_filters_to_terminal_statuses_only_when_no_filter():
    session, captured = _mock_session_capturing_execute()
    await job_service.list_history(session)
    sql = _compiled_sql(captured[0])
    assert "'completed'" in sql
    assert "'failed'" in sql
    assert "'cancelled'" in sql
    assert "'queued'" not in sql
    assert "'processing'" not in sql


@pytest.mark.asyncio
async def test_list_history_with_filter_uses_only_that_status():
    session, captured = _mock_session_capturing_execute()
    await job_service.list_history(session, status_filter="failed")
    sql = _compiled_sql(captured[0])
    assert "'failed'" in sql
    assert "'completed'" not in sql
    assert "'cancelled'" not in sql


@pytest.mark.asyncio
async def test_delete_terminal_jobs_preserves_queued_and_processing():
    session, captured = _mock_session_capturing_execute()
    await job_service.delete_terminal_jobs(session)
    sql = _compiled_sql(captured[0])
    assert sql.startswith("delete from jobs")
    assert "'completed'" in sql
    assert "'failed'" in sql
    assert "'cancelled'" in sql
    assert "'queued'" not in sql
    assert "'processing'" not in sql


# ---------------------------------------------------------------------------
# SP-3 — provider/model/usage/cost fields in history response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_includes_provider_model_usage_cost(client):
    """HistoryResponse exposes translation_provider, translation_model,
    prompt_tokens, completion_tokens, total_tokens, cost_usd."""
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(
        status="completed",
        translation_provider="openrouter",
        translation_model="google/gemini-2.0-flash-001",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.0123,
    )
    with patch("app.api.history.job_service.list_history", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [job]
        resp = await client.get("/api/v1/history")
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["translation_provider"] == "openrouter"
    assert row["translation_model"] == "google/gemini-2.0-flash-001"
    assert row["prompt_tokens"] == 100
    assert row["completion_tokens"] == 50
    assert row["total_tokens"] == 150
    assert row["cost_usd"] == 0.0123


# ---------------------------------------------------------------------------
# Bug fix — History "Model" column was blank for SP-2 jobs.
# SP-2 moved per-job backend config from legacy ORM columns (model_size,
# translation_provider, …) to a `backend_profile` JSON snapshot. The
# History response builder kept reading `job.model_size`, which is no
# longer populated → every post-SP-2 job rendered '—' in the Model column.
# These tests pin the new resolver behaviour.
# ---------------------------------------------------------------------------

from app.api.history import resolve_history_model  # noqa: E402


def test_resolve_history_model_prefers_transcription_model_from_backend_profile():
    """Remote-api jobs ship a `transcription_model` on the snapshot (e.g.
    "large-v3" from the active profile) — that's the truth for the row."""
    job = _make_job(
        model_size=None,
        backend_profile={
            "transcription_backend": "remote-api",
            "transcription_model": "large-v3",
            "whisper_model": "small",  # would be wrong to surface this
        },
    )
    assert resolve_history_model(job) == "large-v3"


def test_resolve_history_model_falls_back_to_whisper_model_for_historical_jobs():
    """Historical jobs (pre-May-2026 local-WhisperX era) have no
    `transcription_model` on the snapshot but DO have `whisper_model`.
    Display layer must read that fallback so old rows still show a model name."""
    job = _make_job(
        model_size=None,
        backend_profile={
            "transcription_model": None,
            "whisper_model": "large-v3",
        },
    )
    assert resolve_history_model(job) == "large-v3"


def test_resolve_history_model_falls_back_to_legacy_model_size_for_pre_sp2_jobs():
    """Old history rows predate SP-2 and have a populated `model_size`
    column + a null `backend_profile`. Keep rendering as before."""
    job = _make_job(model_size="large-v2", backend_profile=None)
    assert resolve_history_model(job) == "large-v2"


def test_resolve_history_model_returns_none_when_nothing_is_populated():
    """A job with neither populated → None → frontend renders '—'."""
    job = _make_job(model_size=None, backend_profile={})
    assert resolve_history_model(job) is None


@pytest.mark.asyncio
async def test_history_endpoint_surfaces_model_from_backend_profile(client):
    """End-to-end through `_to_history_response`: an SP-2 remote-api job
    with `model_size=None` should surface its `transcription_model` from
    the backend_profile in the HistoryResponse `model_size` field."""
    app.dependency_overrides[get_db] = _empty_db
    job = _make_job(
        model_size=None,
        backend_profile={
            "transcription_backend": "remote-api",
            "transcription_model": "large-v3",
            "translation_provider": "ollama",
            "translation_model": "gemma3:27b",
            "name": "Profile1",
        },
    )
    with patch("app.api.history.job_service.list_history", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [job]
        resp = await client.get("/api/v1/history")
    assert resp.status_code == 200
    row = resp.json()[0]
    # The fix: model_size in the response is the RESOLVED model, not the
    # raw (None) ORM column.
    assert row["model_size"] == "large-v3"
