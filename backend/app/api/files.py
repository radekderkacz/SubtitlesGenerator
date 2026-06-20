from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import ApiError
from app.models.orm import Settings
from app.models.schemas import FileBrowseResponse
from app.services import file_browser

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]


@router.get(
    "/files/browse",
    response_model=FileBrowseResponse,
    responses={
        400: {"description": "Path is outside the configured NAS mount root"},
        404: {"description": "Directory not found"},
        422: {"description": "NAS mount path is not configured or missing in the container"},
    },
)
async def browse(session: DbSession, path: Optional[str] = None):
    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings_row = result.scalar_one_or_none()
    if settings_row is None or not settings_row.nas_mount_path:
        return JSONResponse(
            status_code=422,
            content={"detail": "NAS mount path is not configured", "code": "NAS_NOT_CONFIGURED"},
        )

    # Distinguish "the configured NAS root itself is missing in the container"
    # (a misconfiguration — e.g. a stale /shared after the mount moved to /media)
    # from "a requested subdirectory doesn't exist" (a plain 404 below). The
    # former is unfixable by browsing, so give an actionable message instead of
    # a generic "Directory not found".
    if not Path(settings_row.nas_mount_path).is_dir():
        return JSONResponse(
            status_code=422,
            content={
                "detail": (
                    f"Configured media path '{settings_row.nas_mount_path}' isn't available "
                    "inside the app container. The library is mounted at /media — set "
                    "Settings → Media Library to /media."
                ),
                "code": "NAS_ROOT_MISSING",
            },
        )

    try:
        return file_browser.list_directory(path, settings_row.nas_mount_path)
    except ApiError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": e.detail, "code": e.code},
        )
