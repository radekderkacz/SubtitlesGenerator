from sqlalchemy.pool import NullPool

from app.core.database import engine


def test_engine_uses_nullpool() -> None:
    """Regression guard for the 2026-05-16 worker bug: the Celery worker
    runs each task in a fresh ``asyncio.run()`` event loop. A pooled
    asyncpg connection created in one task's loop and reused from the
    next task's loop raises "got Future attached to a different loop /
    another operation is in progress", stranding every job after the
    first. NullPool prevents any connection from outliving its session
    scope (hence its loop), which is what makes the worker safe under
    Celery prefork.

    This is a configuration pin, NOT a behavioral test — exercising the
    actual cross-loop failure needs a real Postgres and two sequential
    ``asyncio.run`` calls (an integration concern). The behavioral proof
    is the post-deploy re-run of the previously-stranded jobs.
    """
    assert isinstance(engine.pool, NullPool)
