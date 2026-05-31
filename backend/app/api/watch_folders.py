"""Watch-folder activity endpoint

Powers the WatchFolderPanel on the Queue Dashboard:

- `auto_enqueued_count_24h` — DB count of jobs with `source="watch_folder"`
  in the last 24 h.
- `recent_auto_jobs` — last 10 watch-folder jobs (any status).
- `recent_skipped` — last 10 paths the watcher saw but skipped because an
  SRT already existed (in-memory ring buffer, lost on restart).
- `monitored_paths` — currently monitored paths from the watcher.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.history import resolve_history_model
from app.core.database import get_db
from app.models.orm import Job
from app.models.schemas import HistoryResponse

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get("/watch-folders/activity")
async def watch_folder_activity(request: Request, session: DbSession) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    count_q = await session.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.source == "watch_folder", Job.created_at >= cutoff)
    )
    auto_count_24h = int(count_q.scalar() or 0)

    recent_q = await session.execute(
        select(Job)
        .where(Job.source == "watch_folder")
        .order_by(Job.created_at.desc())
        .limit(10)
    )
    recent_auto = [
        HistoryResponse(
            id=j.id,
            status=j.status,
            file_path=j.file_path,
            source_language=j.source_language,
            target_language=j.target_language,
            # Single source of truth for the History "Model" column — reads
            # backend_profile (SP-2) with fallback to legacy model_size.
            model_size=resolve_history_model(j),
            srt_path=None,  # the History response computes this; not needed here
            error_message=j.error_message,
            created_at=j.created_at,
            updated_at=j.updated_at,
            completed_at=j.completed_at,
            jellyfin_refreshed_at=j.jellyfin_refreshed_at,
        ).model_dump(mode="json")
        for j in recent_q.scalars().all()
    ]

    watcher = getattr(request.app.state, "watcher", None)
    skipped = watcher.recent_skipped() if watcher is not None else []
    monitored = list(watcher.paths) if watcher is not None else []

    return {
        "auto_enqueued_count_24h": auto_count_24h,
        "recent_auto_jobs": recent_auto,
        "recent_skipped": skipped,
        "monitored_paths": monitored,
    }
