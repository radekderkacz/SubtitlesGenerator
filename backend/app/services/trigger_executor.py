"""Trigger executor — the single chokepoint into `enqueue_job`.

Every trigger fire goes through one path:
    MatchEvent -> file_filter_matches -> dispatch_event -> job_service.enqueue_job

Per the holistic-review seam-bug discipline, NO other code calls enqueue_job
from a trigger-derived event. A grep guard in test_automations_invariants.py
enforces this.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.media import is_video_file
from app.models.orm import Settings, Trigger, TriggerEvent
from app.models.schemas import JobCreate
from redis.exceptions import RedisError

from app.services.job_events import publish_job_update
from app.services.job_service import DuplicateJobError, enqueue_job
from app.services.watcher import has_sibling_srt

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MatchEvent:
    trigger_id: str
    file_path: str
    source_payload: dict


def _scope_prefix(trigger) -> str:
    cfg = getattr(trigger, "config", None) or {}
    t = getattr(trigger, "type", None) or ""
    if t == "watch":
        return cfg.get("path", "/")
    if t == "cron":
        return cfg.get("scan_path", "/")
    if t == "webhook":
        return cfg.get("scope_path") or "/"
    return "/"


def _relativise(file_path: str, prefix: str) -> str:
    if prefix == "/" or not file_path.startswith(prefix.rstrip("/") + "/"):
        return file_path
    return file_path[len(prefix.rstrip("/")) + 1:]


def file_filter_matches(trigger, file_path: str) -> bool:
    """True if the trigger's single file_filter accepts this path."""
    f = getattr(trigger, "file_filter", None) or {"type": "all"}
    ftype = f.get("type", "all")
    if ftype == "all":
        return True
    rel = _relativise(file_path, _scope_prefix(trigger))
    val = (f.get("value") or "")
    if ftype == "subfolder":
        return rel.startswith(val.rstrip("/") + "/")
    if ftype == "name_contains":
        return val.lower() in os.path.basename(file_path).lower()
    return False


async def _get_trigger(
    session: AsyncSession, trigger_id: str
) -> Optional[Trigger]:
    return (
        await session.execute(
            select(Trigger).where(Trigger.id == trigger_id)
        )
    ).scalar_one_or_none()


async def _profile_exists(session: AsyncSession, name: str) -> bool:
    s = (await session.execute(select(Settings))).scalar_one_or_none()
    profs = (s.profiles if s else None) or []
    return any(p.get("name") == name for p in profs)


async def _record_event(
    session: AsyncSession,
    evt: MatchEvent,
    *,
    matched_rule_index: Optional[int],
    outcome: str,
    job_id: Optional[str],
    error: Optional[str],
) -> None:
    session.add(
        TriggerEvent(
            id=str(uuid.uuid4()),
            trigger_id=evt.trigger_id,
            fired_at=datetime.now(timezone.utc),
            event_payload=evt.source_payload | {"file_path": evt.file_path},
            matched_rule_index=matched_rule_index,
            outcome=outcome,
            job_id=job_id,
            error_message=error,
        )
    )
    await session.commit()


async def dispatch_event(session: AsyncSession, evt: MatchEvent) -> str:
    """Single chokepoint into `enqueue_job`. Returns the recorded outcome."""
    trig = await _get_trigger(session, evt.trigger_id)
    if trig is None:
        logger.info("dispatch_event: trigger %s gone — dropping event", evt.trigger_id)
        return "skipped_no_rule"

    # Universal video gate — enforced here so every caller (cron, webhook,
    # watch, manual) gets the same contract. Sidecar files (artwork, .nfo,
    # .srt) would otherwise queue dead jobs.
    if not is_video_file(evt.file_path):
        await _record_event(session, evt, matched_rule_index=None,
                            outcome="skipped_not_video", job_id=None, error=None)
        return "skipped_not_video"

    if not file_filter_matches(trig, evt.file_path):
        await _record_event(session, evt, matched_rule_index=None,
                            outcome="skipped_no_rule", job_id=None, error=None)
        return "skipped_no_rule"

    # Idempotency gates every producer inherits (2026-07 audit R1/R2): a file
    # that already has subtitles, or already has an active job, is a no-op —
    # this is what makes periodic cron re-scans of a whole library safe.
    if has_sibling_srt(evt.file_path):
        await _record_event(session, evt, matched_rule_index=None,
                            outcome="skipped_existing_srt", job_id=None, error=None)
        return "skipped_existing_srt"

    action = trig.action or {}
    profile = action.get("profile_name")
    if not profile or not await _profile_exists(session, profile):
        await _record_event(session, evt, matched_rule_index=None,
                            outcome="failed_dispatch", job_id=None,
                            error=f"profile {profile!r} not found")
        return "failed_dispatch"

    payload = JobCreate(
        file_path=evt.file_path,
        profile_name=profile,
        source_language=action.get("source_language") or "auto",
        translate=action.get("target_language") is not None,
        target_language=action.get("target_language"),
        source=f"trigger:{trig.id}",
    )
    try:
        job = await enqueue_job(session, payload)
    except DuplicateJobError:
        # The DB unique index caught a race the pre-check missed.
        await _record_event(session, evt, matched_rule_index=None,
                            outcome="skipped_duplicate", job_id=None, error=None)
        return "skipped_duplicate"
    # Surface the new queued job on the live Queue immediately (the SSE stream
    # is persistent and isn't refetched on navigation). Best-effort: the row is
    # already committed, so a Redis hiccup must not fail the dispatch.
    try:
        await publish_job_update(job)
    except (RedisError, OSError):
        logger.warning("trigger job %s created but live publish failed", job.id, exc_info=True)
    await _record_event(session, evt, matched_rule_index=None,
                        outcome="submitted", job_id=job.id, error=None)
    return "submitted"
