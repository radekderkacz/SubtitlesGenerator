from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import app_settings

# NullPool: never pool connections. The Celery worker runs each task via a
# fresh ``asyncio.run()`` (new event loop per task); a pooled asyncpg
# connection created in one task's loop, then reused from the next task's
# loop, raises "got Future attached to a different loop / another operation
# is in progress" and strands every job after the first (2026-05-16). With
# NullPool each session opens a connection in the *current* loop and closes
# it on scope exit, so no connection ever crosses an event loop. All
# callers (worker helpers, get_db, SSE) already use short ``async with``
# scopes, so the loss of pooling is immaterial at this app's scale.
engine = create_async_engine(
    app_settings.database_url, echo=False, poolclass=NullPool
)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
