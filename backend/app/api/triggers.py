"""CRUD endpoints for Automations Triggers."""
import os
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.media import is_video_file
from app.models.orm import Settings, TriggerEvent
from app.models.schemas import (
    ScheduleSchema,
    TriggerCreate,
    TriggerEventResponse,
    TriggerResponse,
    TriggerSecretResponse,
    TriggerUpdate,
)
from app.services import trigger_service
from app.services.cron_scheduler import MAX_FILES_PER_FIRE, schedule_to_cron
from app.services.trigger_executor import MatchEvent, dispatch_event

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]

_TRIGGER_NOT_FOUND = {"detail": "trigger not found", "code": "TRIGGER_NOT_FOUND"}


@router.get(
    "/triggers/events",
    responses={200: {"description": "Recent trigger events across all triggers"}},
)
async def list_trigger_events(
    session: DbSession,
    outcome: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TriggerEventResponse]:
    stmt = (
        select(TriggerEvent)
        .order_by(TriggerEvent.fired_at.desc())
        .limit(limit)
    )
    if outcome:
        stmt = stmt.where(TriggerEvent.outcome == outcome)
    rows = (await session.execute(stmt)).scalars().all()
    return [TriggerEventResponse.model_validate(r) for r in rows]


async def _profile_names(session: AsyncSession) -> set[str]:
    s = (await session.execute(select(Settings))).scalar_one_or_none()
    profs = (s.profiles if s else None) or []
    return {p.get("name") for p in profs if p.get("name")}


async def _to_response(session: AsyncSession, t) -> TriggerResponse:
    last, count = await trigger_service._derive_stats(session, t.id)
    return TriggerResponse(
        id=t.id,
        name=t.name,
        type=t.type,
        config=t.config,
        action=t.action,
        file_filter=t.file_filter,
        enabled=t.enabled,
        created_at=t.created_at,
        updated_at=t.updated_at,
        last_fired_at=last,
        fire_count_24h=count,
    )


@router.post(
    "/triggers",
    status_code=201,
    responses={
        201: {"description": "Trigger created"},
        422: {"description": "Validation error or unknown profile"},
    },
)
async def create_trigger(payload: TriggerCreate, session: DbSession):
    try:
        t = await trigger_service.create_trigger(
            session, payload, await _profile_names(session)
        )
    except trigger_service.ProfileNotFoundError as e:
        return JSONResponse(
            status_code=422, content={"detail": str(e), "code": "PROFILE_NOT_FOUND"}
        )
    return await _to_response(session, t)


@router.get(
    "/triggers",
    responses={200: {"description": "List all triggers"}},
)
async def list_triggers(session: DbSession):
    items = await trigger_service.list_triggers(session)
    return [await _to_response(session, t) for t in items]


@router.get(
    "/triggers/{trigger_id}",
    responses={
        200: {"description": "Trigger detail"},
        404: {"description": "Trigger not found"},
    },
)
async def get_trigger(trigger_id: str, session: DbSession):
    t = await trigger_service.get_trigger(session, trigger_id)
    if t is None:
        return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)
    return await _to_response(session, t)


@router.patch(
    "/triggers/{trigger_id}",
    responses={
        200: {"description": "Updated"},
        404: {"description": "Not found"},
        422: {"description": "Validation"},
    },
)
async def update_trigger(trigger_id: str, payload: TriggerUpdate, session: DbSession):
    try:
        t = await trigger_service.update_trigger(
            session, trigger_id, payload, await _profile_names(session)
        )
    except trigger_service.ProfileNotFoundError as e:
        return JSONResponse(
            status_code=422, content={"detail": str(e), "code": "PROFILE_NOT_FOUND"}
        )
    if t is None:
        return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)
    return await _to_response(session, t)


@router.delete(
    "/triggers/{trigger_id}",
    responses={
        204: {"description": "Deleted"},
        404: {"description": "Not found"},
    },
)
async def delete_trigger(trigger_id: str, session: DbSession):
    ok = await trigger_service.delete_trigger(session, trigger_id)
    if not ok:
        return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)
    return Response(status_code=204)


@router.get(
    "/triggers/{trigger_id}/secret",
    responses={
        200: {"description": "Webhook secret"},
        404: {"description": "Not found"},
        400: {"description": "Non-webhook trigger"},
    },
)
async def reveal_secret(trigger_id: str, session: DbSession):
    secret = await trigger_service.reveal_secret(session, trigger_id)
    if secret is None:
        t = await trigger_service.get_trigger(session, trigger_id)
        if t is None:
            return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)
        return JSONResponse(
            status_code=400,
            content={
                "detail": "trigger has no webhook secret",
                "code": "NOT_A_WEBHOOK_TRIGGER",
            },
        )
    return TriggerSecretResponse(webhook_secret=secret)


@router.post(
    "/triggers/{trigger_id}/fire",
    responses={
        200: {"description": "Manual scan completed"},
        400: {"description": "Webhook triggers cannot self-fire"},
        404: {"description": "Trigger not found"},
    },
)
async def fire_trigger(trigger_id: str, session: DbSession):
    trig = await trigger_service.get_trigger(session, trigger_id)
    if trig is None:
        return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)
    if trig.type == "webhook":
        return JSONResponse(
            status_code=400,
            content={
                "detail": "webhook triggers fire only via inbound POST",
                "code": "MANUAL_FIRE_NOT_SUPPORTED",
            },
        )
    scope = (trig.config or {}).get("path") or (trig.config or {}).get("scan_path")
    fired = 0
    for root, _dirs, files in os.walk(scope):
        for f in files:
            fp = os.path.join(root, f)
            # Only video files are transcribable — silently skip sidecar
            # files (.srt, .jpg, .nfo) so a manual fire never submits them.
            if not is_video_file(fp):
                continue
            if fired >= MAX_FILES_PER_FIRE:
                break
            await dispatch_event(
                session,
                MatchEvent(
                    trigger_id=trigger_id,
                    file_path=fp,
                    source_payload={"manual_fire": True},
                ),
            )
            fired += 1
    return {"fired": fired}


class _CronPreviewRequest(BaseModel):
    schedule: ScheduleSchema
    count: int = 3


@router.post(
    "/triggers/cron/preview",
    responses={
        200: {"description": "Next N fire timestamps for a schedule object"},
        422: {"description": "Invalid schedule"},
    },
)
async def preview_cron(payload: _CronPreviewRequest):
    from datetime import datetime, timezone
    from croniter import croniter

    count = max(1, min(payload.count, 10))
    try:
        expr = schedule_to_cron(payload.schedule.model_dump())
    except (ValueError, KeyError) as exc:
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "code": "INVALID_SCHEDULE"},
        )
    now = datetime.now(timezone.utc)
    it = croniter(expr, now)
    nexts = [it.get_next(datetime).isoformat() for _ in range(count)]
    return {"next_fires": nexts}
