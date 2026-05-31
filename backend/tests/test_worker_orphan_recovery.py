"""Unit tests for `app.worker.orphan_recovery`.

The signal handler itself is hard to exercise without a real Celery worker
(and pragma'd `no cover`); these tests cover the underlying async sweep —
the part that actually carries the policy — by mocking AsyncSessionLocal +
`generate_subtitles.delay`.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.worker import orphan_recovery


def _fake_session(orphans):
    """Build an AsyncMock standing in for an `AsyncSession` opened by
    `async with AsyncSessionLocal() as session`.

    `session.execute(...)` returns a result whose `.scalars().all()` yields
    `orphans`. `commit` is awaited; `add`/`refresh` etc. are unused here.
    """
    scalars = MagicMock()
    scalars.all = MagicMock(return_value=orphans)
    result = MagicMock()
    result.scalars = MagicMock(return_value=scalars)
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


def _async_session_factory(session):
    """Replacement for `AsyncSessionLocal`. Used as `AsyncSessionLocal()` →
    async context manager yielding `session`."""
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock(return_value=cm)
    return factory


def _make_orphan(job_id: str, age_seconds: int, phase: str = "transcribing", progress: int = 20):
    """Plain attribute container that quacks like an ORM Job for the sweep
    code. Only the fields the sweep reads/writes need to exist."""
    return SimpleNamespace(
        id=job_id,
        status="processing",
        phase=phase,
        progress=progress,
        updated_at=datetime.now(timezone.utc) - timedelta(seconds=age_seconds),
        error_message=None,
    )


@pytest.mark.asyncio
async def test_recover_orphans_requeues_and_dispatches_each_orphan():
    """Two orphan rows older than the cutoff → both reset to queued and
    re-dispatched via `generate_subtitles.delay`."""
    orphans = [
        _make_orphan("job-A", age_seconds=120),
        _make_orphan("job-B", age_seconds=600, phase="translating", progress=65),
    ]
    session = _fake_session(orphans)
    dispatched = []
    fake_task = MagicMock()
    fake_task.delay = MagicMock(side_effect=lambda jid: dispatched.append(jid))
    with patch(
        "app.core.database.AsyncSessionLocal", _async_session_factory(session)
    ), patch("app.worker.tasks.generate_subtitles", fake_task):
        count = await orphan_recovery._recover_orphans()

    assert count == 2
    # Each orphan was mutated to the recovery shape BEFORE commit.
    for job in orphans:
        assert job.status == "queued"
        assert job.phase is None
        assert job.progress == 0
        assert job.error_message == "Auto-recovered after worker restart"
    # Commit happened exactly once; dispatch happened once per orphan, in order.
    session.commit.assert_awaited_once()
    assert dispatched == ["job-A", "job-B"]


@pytest.mark.asyncio
async def test_recover_orphans_no_orphans_returns_zero_and_does_not_dispatch():
    """Clean DB → no commit, no dispatch, returns 0."""
    session = _fake_session([])
    fake_task = MagicMock()
    fake_task.delay = MagicMock()
    with patch(
        "app.core.database.AsyncSessionLocal", _async_session_factory(session)
    ), patch("app.worker.tasks.generate_subtitles", fake_task):
        count = await orphan_recovery._recover_orphans()

    assert count == 0
    # No commit needed when there's nothing to recover.
    session.commit.assert_not_awaited()
    fake_task.delay.assert_not_called()


@pytest.mark.asyncio
async def test_recover_orphans_dispatch_happens_after_commit():
    """A network call to Celery (`delay`) must NOT happen until after the
    DB rows have been committed — otherwise the freshly-dispatched task
    can race with the not-yet-committed `queued` status."""
    orphans = [_make_orphan("race-job", age_seconds=90)]
    session = _fake_session(orphans)
    sequence = []
    session.commit = AsyncMock(side_effect=lambda: sequence.append("commit"))
    fake_task = MagicMock()
    fake_task.delay = MagicMock(side_effect=lambda jid: sequence.append(f"delay:{jid}"))
    with patch(
        "app.core.database.AsyncSessionLocal", _async_session_factory(session)
    ), patch("app.worker.tasks.generate_subtitles", fake_task):
        await orphan_recovery._recover_orphans()

    assert sequence == ["commit", "delay:race-job"]


def test_orphan_age_threshold_is_30s():
    """Pin the policy threshold so a future refactor that loosens it makes
    a deliberate, reviewable change rather than a silent one."""
    assert orphan_recovery.ORPHAN_AGE_SECONDS == 30
