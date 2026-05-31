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
        422: {"description": "NAS mount path is not configured"},
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

    try:
        return file_browser.list_directory(path, settings_row.nas_mount_path)
    except ApiError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": e.detail, "code": e.code},
        )
