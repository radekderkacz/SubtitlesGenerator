"""Cron executor — the periodic Beat task body.

A SINGLE Celery Beat schedule (`crontab(minute='*')`) calls this every minute.
The task evaluates ALL enabled cron triggers in one pass and fires those whose
`croniter(expr, last_fire_at).get_next() <= now`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from croniter import croniter
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.core.database import AsyncSessionLocal as _SessionLocal
from app.core.media import is_video_file
from app.models.orm import Trigger, TriggerEvent
from app.services.trigger_executor import MatchEvent, dispatch_event
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)

# Configurable cap (env override) so a misconfigured scan_path can't blow up
# the worker. Excess files → skipped_scan_limit events, one per excess.
MAX_FILES_PER_FIRE = int(os.environ.get("AUTOMATIONS_CRON_SCAN_LIMIT", "500"))
# A video whose mtime is younger than this is assumed to still be copying —
# transcribing a half-copied file "completes" with subtitles for a fraction
# of the movie. The next scheduled scan picks it up once it settles.
CRON_MIN_FILE_AGE_SECONDS = 60.0


def schedule_to_cron(schedule: dict) -> str:
    """Convert a UI schedule object into a 5-field cron string.

    The ONLY schedule->cron conversion in the codebase — backend-side so the
    frontend never has to (no drift). Raises ValueError on an unknown mode so
    a future mode added without a conversion fails loudly.
    """
    mode = schedule.get("mode")
    if mode == "hourly":
        return f"0 */{schedule['every_n_hours']} * * *"
    hh, mm = (schedule.get("time") or "00:00").split(":")
    hh, mm = int(hh), int(mm)
    if mode == "daily":
        return f"{mm} {hh} * * *"
    if mode == "weekly":
        return f"{mm} {hh} * * {schedule['day_of_week']}"
    if mode == "monthly":
        return f"{mm} {hh} {schedule['day_of_month']} * *"
    raise ValueError(f"unknown schedule mode: {mode!r}")


async def _load_cron_triggers() -> list[Trigger]:
    async with _SessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(Trigger).where(
                        Trigger.type == "cron", Trigger.enabled.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )


async def _last_fire_at(trigger_id: str) -> Optional[datetime]:
    async with _SessionLocal() as session:
        return (
            await session.execute(
                select(func.max(TriggerEvent.fired_at)).where(
                    TriggerEvent.trigger_id == trigger_id
                )
            )
        ).scalar_one()


async def _record_skipped_scan_limit(
    trigger_id: str, file_path: str, scan_path: str
) -> None:
    async with _SessionLocal() as session:
        session.add(
            TriggerEvent(
                id=str(uuid.uuid4()),
                trigger_id=trigger_id,
                fired_at=datetime.now(timezone.utc),
                event_payload={"file_path": file_path, "scan_path": scan_path},
                matched_rule_index=None,
                outcome="skipped_scan_limit",
                job_id=None,
                error_message=None,
            )
        )
        await session.commit()


def _is_still_copying(fp: str, now: datetime) -> bool:
    """True when the file was modified within the settle window (a copy in
    progress). Stat failures count as settled — dispatch_event re-validates."""
    try:
        return now.timestamp() - os.path.getmtime(fp) < CRON_MIN_FILE_AGE_SECONDS
    except OSError:
        return False


async def _stamp_last_fired(trigger_id: str, now: datetime) -> None:
    """Record the fire on the trigger row itself, so a scan that dispatched
    nothing still counts as fired (no TriggerEvent row exists to prove it)."""
    async with _SessionLocal() as session:
        row = await session.get(Trigger, trigger_id)
        if row is not None:
            row.last_fired_at = now
            await session.commit()


async def _fire_cron_trigger(trig: Trigger, now: datetime) -> None:
    scan_path = trig.config["scan_path"]
    fired = 0
    async with _SessionLocal() as session:
        for root, _dirs, files in os.walk(scan_path):
            for f in files:
                fp = os.path.join(root, f)
                # Only video files are transcribable. Sidecar files (.srt,
                # .jpg, .nfo) are silently skipped — no event row, and they
                # do not consume the scan-limit budget.
                if not is_video_file(fp):
                    continue
                if _is_still_copying(fp, now):
                    logger.info("cron %s: %s modified <%ss ago — still copying, "
                                "next scan picks it up", trig.id, fp,
                                int(CRON_MIN_FILE_AGE_SECONDS))
                    continue
                if fired >= MAX_FILES_PER_FIRE:
                    await _record_skipped_scan_limit(trig.id, fp, scan_path)
                    continue
                await dispatch_event(
                    session,
                    MatchEvent(
                        trigger_id=trig.id,
                        file_path=fp,
                        source_payload={
                            "scheduled_at": now.isoformat(),
                            "scan_path": scan_path,
                        },
                    ),
                )
                fired += 1
    await _stamp_last_fired(trig.id, now)


async def _evaluate_async(now: datetime) -> None:
    triggers = await _load_cron_triggers()
    for trig in triggers:
        try:
            last = await _last_fire_at(trig.id)
            # The row stamp covers fires whose scan dispatched nothing (no
            # TriggerEvent exists for those).
            stamp = getattr(trig, "last_fired_at", None)
            if isinstance(stamp, datetime) and (last is None or stamp > last):
                last = stamp
            # When no prior fire: assume the trigger was "just enabled" and
            # should fire this minute — subtract 1m so get_next() <= now.
            base = last or (now.replace(second=0, microsecond=0) - timedelta(minutes=1))
            nxt = croniter(trig.config["cron"], base).get_next(datetime)
            if nxt > now:
                continue
            await _fire_cron_trigger(trig, now)
        except (DBAPIError, ValueError, OSError, KeyError) as exc:
            # KeyError: a malformed config (missing cron/scan_path) must not
            # halt evaluation of the remaining triggers (2026-07 audit R9).
            logger.error(
                "cron_scheduler: trigger %s evaluation failed: %s", trig.id, exc
            )


@celery_app.task(name="evaluate_cron_triggers")
def evaluate_cron_triggers() -> None:
    asyncio.run(_evaluate_async(datetime.now(timezone.utc)))
