"""GET /api/v1/watch-folders/activity tests."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.database import get_db
from app.main import app
from app.models.orm import Job


def _make_job(**kwargs) -> Job:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        status="completed",
        phase=None,
        progress=100,
        file_path="/media/films/Foo.mkv",
        source_language=None,
        target_language="en",
        model_size="large-v3",
        translation_provider=None,
        translation_model=None,
        log_path=None,
        error_message=None,
        source="watch_folder",
        created_at=now,
        updated_at=now,
        completed_at=now,
        jellyfin_refreshed_at=None,
    )
    defaults.update(kwargs)
    return Job(**defaults)


@pytest.fixture
def _db_session_with_count_then_jobs():
    """Returns an async generator that yields a session whose `execute` first
    returns a count, then a list of Job rows. Used to exercise the two
    sequential queries in the endpoint."""

    def make(count: int, jobs: list[Job]):
        async def _override():
            session = AsyncMock()
            count_result = MagicMock()
            count_result.scalar = MagicMock(return_value=count)
            jobs_result = MagicMock()
            jobs_result.scalars = MagicMock(
                return_value=MagicMock(all=MagicMock(return_value=jobs))
            )
            session.execute = AsyncMock(side_effect=[count_result, jobs_result])
            yield session

        return _override

    return make


@pytest.mark.asyncio
async def test_activity_endpoint_returns_count_jobs_and_watcher_state(
    client, _db_session_with_count_then_jobs,
):
    j1 = _make_job(file_path="/x/Auto1.mkv")
    j2 = _make_job(file_path="/x/Auto2.mkv")

    fake_watcher = MagicMock()
    fake_watcher.paths = ("/media/incoming",)
    fake_watcher.recent_skipped.return_value = [
        {"path": "/media/incoming/Bar.mkv", "skipped_at": "2026-05-08T12:00:00+00:00"},
    ]
    app.state.watcher = fake_watcher

    app.dependency_overrides[get_db] = _db_session_with_count_then_jobs(7, [j1, j2])
    response = await client.get("/api/v1/watch-folders/activity")

    assert response.status_code == 200
    body = response.json()
    assert body["auto_enqueued_count_24h"] == 7
    assert len(body["recent_auto_jobs"]) == 2
    assert body["recent_auto_jobs"][0]["file_path"] == "/x/Auto1.mkv"
    assert body["recent_skipped"][0]["path"] == "/media/incoming/Bar.mkv"
    assert body["monitored_paths"] == ["/media/incoming"]


@pytest.mark.asyncio
async def test_activity_endpoint_handles_no_watcher_gracefully(
    client, _db_session_with_count_then_jobs,
):
    """If the watcher singleton was never set (test boot), don't 500."""
    if hasattr(app.state, "watcher"):
        del app.state.watcher

    app.dependency_overrides[get_db] = _db_session_with_count_then_jobs(0, [])
    response = await client.get("/api/v1/watch-folders/activity")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "auto_enqueued_count_24h": 0,
        "recent_auto_jobs": [],
        "recent_skipped": [],
        "monitored_paths": [],
    }


@pytest.mark.asyncio
async def test_activity_endpoint_uses_24h_cutoff_in_query(
    client, _db_session_with_count_then_jobs,
):
    """The query should filter created_at >= now-24h. Inspect the SQL."""
    captured: list = []

    async def _override():
        session = AsyncMock()

        async def execute(stmt, *_a, **_k):
            captured.append(stmt)
            r = MagicMock()
            r.scalar = MagicMock(return_value=0)
            r.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
            return r

        session.execute = execute
        yield session

    app.dependency_overrides[get_db] = _override
    response = await client.get("/api/v1/watch-folders/activity")
    assert response.status_code == 200
    # First captured statement is the count query — should reference watch_folder
    sql = str(captured[0].compile(compile_kwargs={"literal_binds": True})).lower()
    assert "watch_folder" in sql
    assert "created_at" in sql
