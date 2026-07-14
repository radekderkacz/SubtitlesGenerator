"""Public webhook endpoint — `POST /api/v1/triggers/{id}/webhook`.

Bearer-validated INSIDE the handler (no FastAPI auth dependency — Bearer is
the only gate). Auth failures and bad payloads STILL record `trigger_events`
rows with outcome='failed_dispatch' for activity-feed visibility.
"""
from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.orm import TriggerEvent
from app.services import trigger_service
from app.services.trigger_executor import MatchEvent, dispatch_event

router = APIRouter()

DbSession = Annotated[AsyncSession, Depends(get_db)]

_TRIGGER_NOT_FOUND = {"detail": "trigger not found", "code": "TRIGGER_NOT_FOUND"}


async def _record_auth_failure(
    session: AsyncSession, trigger_id: str, ip: str
) -> None:
    session.add(
        TriggerEvent(
            id=str(uuid.uuid4()),
            trigger_id=trigger_id,
            fired_at=datetime.now(timezone.utc),
            event_payload={"ip": ip},
            outcome="failed_dispatch",
            job_id=None,
            error_message="invalid signature",
        )
    )
    await session.commit()


async def _record_missing_path(
    session: AsyncSession, trigger_id: str, body: dict, ip: str
) -> None:
    session.add(
        TriggerEvent(
            id=str(uuid.uuid4()),
            trigger_id=trigger_id,
            fired_at=datetime.now(timezone.utc),
            event_payload={"request_body": body, "ip": ip},
            outcome="failed_dispatch",
            job_id=None,
            error_message="missing required field: file_path",
        )
    )
    await session.commit()


@router.post(
    "/triggers/{trigger_id}/webhook",
    responses={
        200: {"description": "Event accepted + dispatched"},
        400: {"description": "Missing file_path"},
        401: {"description": "Invalid Bearer signature"},
        404: {"description": "Trigger not found"},
    },
)
async def receive_webhook(
    trigger_id: str,
    request: Request,
    session: DbSession,
    authorization: Annotated[str | None, Header()] = None,
):
    trig = await trigger_service.get_trigger(session, trigger_id)
    if trig is None:
        return JSONResponse(status_code=404, content=_TRIGGER_NOT_FOUND)

    expected = trig.webhook_secret or ""
    presented = ""
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer "):]

    ip = request.client.host if request.client else "?"
    if not expected or not hmac.compare_digest(expected, presented):
        await _record_auth_failure(session, trigger_id, ip)
        return JSONResponse(
            status_code=401,
            content={
                "detail": "invalid signature",
                "code": "WEBHOOK_AUTH_FAILED",
            },
        )

    try:
        body = await request.json()
    except ValueError:
        # json.JSONDecodeError / UnicodeDecodeError (both ValueError) — the
        # client sent a non-JSON body.
        return JSONResponse(
            status_code=400,
            content={"detail": "request body is not valid JSON",
                     "code": "WEBHOOK_BAD_JSON"},
        )
    if not isinstance(body, dict) or "file_path" not in body or not isinstance(body["file_path"], str):
        await _record_missing_path(session, trigger_id, body, ip)
        return JSONResponse(
            status_code=400,
            content={
                "detail": "missing required field: file_path",
                "code": "WEBHOOK_MISSING_FIELD",
            },
        )

    outcome = await dispatch_event(
        session,
        MatchEvent(
            trigger_id=trigger_id,
            file_path=body["file_path"],
            source_payload={"request_body": body, "ip": ip},
        ),
    )
    return {"outcome": outcome}
