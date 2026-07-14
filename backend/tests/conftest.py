import os

# Set required env vars before any app imports so pydantic-settings resolves them.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_BROKER_URL", "redis://localhost:6379/0")
os.environ.setdefault("CELERY_RESULT_BACKEND", "redis://localhost:6379/0")

from sqlalchemy import create_engine, text as sa_text
from alembic.config import Config as AlembicConfig
from alembic import command as alembic_command

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.models.orm import Job, Settings

pytest_plugins = ["pytest_asyncio"]


@pytest_asyncio.fixture
async def client():
    """Async test client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac


@pytest.fixture
def make_settings_row():
    def _factory(**kwargs) -> Settings:
        now = datetime.now(timezone.utc)
        defaults = dict(
            id=1,
            nas_mount_path="/media",
            jellyfin_url=None,
            jellyfin_api_key=None,
            transcription_backend=None,
            transcription_api_url="http://whisper.test/v1",
            transcription_model=None,
            transcription_api_key=None,
            translation_provider=None,
            translation_model=None,
            translation_api_key=None,
            translation_api_url=None,
            hf_token=None,
            created_at=now,
            updated_at=now,
        )
        defaults.update(kwargs)
        return Settings(**defaults)
    return _factory


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def mock_session_factory():
    """Generic AsyncSession factory for service-layer tests.

    Usage::

        session, added = mock_session_factory(settings=<mock>)
        session, added = mock_session_factory(existing_job=<dict>)

    Keyword arguments
    -----------------
    settings
        Object whose `.profiles`, `.whisper_model`, `.whisper_device` etc.
        are readable. Returned by ``await session.execute(select(Settings)...)
        .scalar_one_or_none()``.
    existing_job
        Dict of Job field values.  When provided, ``await session.get(Job, id)``
        returns a real ``Job(**existing_job)`` instance (used by Task 4 retry
        path).  When omitted, ``session.get`` returns ``None``.

    Returns a ``(session, added_rows)`` tuple.
    ``added_rows`` accumulates every argument passed to ``session.add()``.
    """
    def _make(*, settings=None, existing_job=None):
        added_rows = []

        session = AsyncMock()

        # execute(select(Settings).where(...)) → result.scalar_one_or_none() → settings
        exec_result = MagicMock()
        exec_result.scalar_one_or_none = MagicMock(return_value=settings)
        # execute(select(Job.id).where(...)) → result.first() → None
        # (the WS5 active-duplicate pre-check finds no existing job by default)
        exec_result.first = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=exec_result)

        # session.get(Job, id) → Job instance (or None)
        job_obj = Job(**existing_job) if existing_job is not None else None
        session.get = AsyncMock(return_value=job_obj)

        # session.add is sync in SQLAlchemy; side_effect captures every call
        session.add = MagicMock(side_effect=added_rows.append)

        session.commit = AsyncMock()
        # refresh is a no-op — the returned Job object is already populated
        session.refresh = AsyncMock()

        return session, added_rows

    return _make


@pytest.fixture
def db_engine_sync():
    """Sync engine for alembic + Inspector tests.

    Strips the asyncpg driver from DATABASE_URL so alembic + psycopg2 work
    (alembic doesn't use the asyncpg driver). The test runs against a real
    Postgres instance — if DATABASE_URL points at localhost, ensure pg is up.
    """
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "")
    eng = create_engine(url)
    # Start each test at a known baseline: clean schema, then run migrations
    # to 0007 (the pre-0008 state); each test calls command.upgrade("0008")
    # itself to exercise the migration under test.
    with eng.begin() as conn:
        conn.execute(sa_text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa_text("CREATE SCHEMA public"))
    cfg = AlembicConfig("backend/alembic.ini")
    cfg.set_main_option("script_location", "backend/alembic")
    alembic_command.upgrade(cfg, "0007")
    yield eng
    eng.dispose()
