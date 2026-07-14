"""Trigger CRUD + secret + derived fire stats.

Publishes a JSON blob on the `subtitles:trigger_updates` Redis channel after
every mutation so `watcher.py` can live-reload its observers without an app
restart. Channel payload: {"action": "created"|"updated"|"deleted", "trigger_id": "<uuid>"}.
"""
from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import app_settings
from app.models.orm import Trigger, TriggerEvent
from app.models.schemas import TriggerCreate, TriggerUpdate
from app.services.cron_scheduler import schedule_to_cron

TRIGGER_UPDATES_CHANNEL = "subtitles:trigger_updates"


class ProfileNotFoundError(Exception):
    def __init__(self, name: str):
        super().__init__(f"profile '{name}' not found in Settings.profiles")
        self.name = name


async def _publish_update(action: str, trigger_id: str) -> None:
    r = aioredis.from_url(app_settings.redis_url)
    try:
        await r.publish(
            TRIGGER_UPDATES_CHANNEL,
            json.dumps({"action": action, "trigger_id": trigger_id}),
        )
    finally:
        await r.aclose()


def _validate_action_profile(action, profile_names: set[str]) -> None:
    # Empty profile_name is allowed — means "use default / no profile".
    # Only validate when a non-empty name is specified.
    if action and action.profile_name and action.profile_name not in profile_names:
        raise ProfileNotFoundError(action.profile_name)


def _validated_cron_config(cfg: dict) -> dict:
    """A cron trigger config must carry a parseable derived cron expression
    and a scan_path — a config that loses either KeyErrors every Beat
    evaluation forever (2026-07 audit R9)."""
    from croniter import croniter

    if not cfg.get("cron"):
        raise ValueError("cron trigger config requires a schedule")
    croniter(cfg["cron"])  # raises ValueError on a malformed expression
    if not cfg.get("scan_path"):
        raise ValueError("cron trigger config requires scan_path")
    return cfg


async def create_trigger(
    session: AsyncSession, payload: TriggerCreate, profile_names: set[str]
) -> Trigger:
    _validate_action_profile(payload.action, profile_names)

    config_to_store = payload.config
    if payload.type.value == "cron":
        cfg = dict(payload.config)
        cfg["cron"] = schedule_to_cron(cfg["schedule"])
        config_to_store = _validated_cron_config(cfg)

    t = Trigger(
        id=str(uuid.uuid4()),
        name=payload.name,
        type=payload.type.value,
        config=config_to_store,
        action=payload.action.model_dump(),
        file_filter=payload.file_filter.model_dump(),
        enabled=payload.enabled,
        webhook_secret=secrets.token_hex(32) if payload.type.value == "webhook" else None,
    )
    session.add(t)
    await session.commit()
    await session.refresh(t)
    await _publish_update("created", t.id)
    return t


async def _derive_stats(
    session: AsyncSession, trigger_id: str
) -> tuple[Optional[datetime], int]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    last = (
        await session.execute(
            select(func.max(TriggerEvent.fired_at)).where(
                TriggerEvent.trigger_id == trigger_id
            )
        )
    ).scalar_one()
    count24 = (
        await session.execute(
            select(func.count())
            .select_from(TriggerEvent)
            .where(
                TriggerEvent.trigger_id == trigger_id,
                TriggerEvent.fired_at >= cutoff,
            )
        )
    ).scalar_one()
    return last, int(count24)


async def get_trigger(
    session: AsyncSession, trigger_id: str
) -> Optional[Trigger]:
    return (
        await session.execute(select(Trigger).where(Trigger.id == trigger_id))
    ).scalar_one_or_none()


async def list_triggers(session: AsyncSession) -> list[Trigger]:
    return list(
        (
            await session.execute(
                select(Trigger).order_by(Trigger.created_at.asc())
            )
        )
        .scalars()
        .all()
    )


async def update_trigger(
    session: AsyncSession,
    trigger_id: str,
    payload: TriggerUpdate,
    profile_names: set[str],
) -> Optional[Trigger]:
    t = await get_trigger(session, trigger_id)
    if t is None:
        return None
    if payload.action is not None:
        _validate_action_profile(payload.action, profile_names)
        t.action = payload.action.model_dump()
    if payload.file_filter is not None:
        t.file_filter = payload.file_filter.model_dump()
    if payload.name is not None:
        t.name = payload.name
    if payload.config is not None:
        config_to_store = payload.config
        if t.type == "cron":
            cfg = dict(payload.config)
            if "schedule" in cfg:
                cfg["cron"] = schedule_to_cron(cfg["schedule"])
            elif "cron" not in cfg and isinstance(t.config, dict) and "cron" in t.config:
                # An update that omits the schedule keeps the derived cron —
                # storing a config without it bricked the trigger silently.
                cfg["cron"] = t.config["cron"]
            config_to_store = _validated_cron_config(cfg)
        t.config = config_to_store
    if payload.enabled is not None:
        t.enabled = payload.enabled
    await session.commit()
    await session.refresh(t)
    await _publish_update("updated", t.id)
    return t


async def delete_trigger(session: AsyncSession, trigger_id: str) -> bool:
    t = await get_trigger(session, trigger_id)
    if t is None:
        return False
    await session.delete(t)
    await session.commit()
    await _publish_update("deleted", trigger_id)
    return True


async def reveal_secret(session: AsyncSession, trigger_id: str) -> Optional[str]:
    t = await get_trigger(session, trigger_id)
    return t.webhook_secret if t else None
