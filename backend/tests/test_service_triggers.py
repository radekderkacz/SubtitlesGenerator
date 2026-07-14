import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from app.services import trigger_service
from app.models.orm import Trigger
from app.models.schemas import TriggerCreate, TriggerUpdate, ActionSchema, FileFilterSchema


@pytest.mark.asyncio
async def test_create_watch_trigger_no_secret():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    payload = TriggerCreate(
        name="TV", type="watch", config={"path": "/shared/TV"},
        action=ActionSchema(profile_name="P1", source_language=None, target_language=None, skip_if_srt=True),
        file_filter=FileFilterSchema(type="all", value=None),
    )
    with patch.object(trigger_service, "_publish_update", new=AsyncMock()) as pub:
        t = await trigger_service.create_trigger(session, payload, profile_names={"P1"})
    assert t.type == "watch"
    assert t.webhook_secret is None
    pub.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_webhook_trigger_generates_64char_secret():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    payload = TriggerCreate(
        name="hook", type="webhook", config={},
        action=ActionSchema(profile_name="P1", source_language=None, target_language=None, skip_if_srt=True),
    )
    with patch.object(trigger_service, "_publish_update", new=AsyncMock()):
        t = await trigger_service.create_trigger(session, payload, profile_names={"P1"})
    assert t.webhook_secret is not None
    assert len(t.webhook_secret) == 64  # 32 bytes hex


@pytest.mark.asyncio
async def test_create_rejects_action_with_unknown_profile():
    session = AsyncMock()
    payload = TriggerCreate(
        name="x", type="watch", config={"path": "/x"},
        action=ActionSchema(profile_name="MISSING", source_language=None, target_language=None, skip_if_srt=True),
    )
    with pytest.raises(trigger_service.ProfileNotFoundError):
        await trigger_service.create_trigger(session, payload, profile_names={"P1"})


def _make_trigger(**kwargs) -> MagicMock:
    now = datetime.now(timezone.utc)
    defaults = dict(
        id=str(uuid.uuid4()),
        name="test",
        type="watch",
        config={"path": "/shared"},
        action=None,
        file_filter=None,
        enabled=True,
        webhook_secret=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(kwargs)
    t = MagicMock(spec=Trigger)
    for k, v in defaults.items():
        setattr(t, k, v)
    return t


@pytest.mark.asyncio
async def test_update_preserves_secret():
    existing = _make_trigger(type="webhook", webhook_secret="abc123secret")

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=existing)
    session.execute = AsyncMock(return_value=exec_result)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()

    payload = TriggerUpdate(name="renamed")
    with patch.object(trigger_service, "_publish_update", new=AsyncMock()):
        t = await trigger_service.update_trigger(session, existing.id, payload, profile_names=set())

    assert t is not None
    assert t.webhook_secret == "abc123secret"
    assert t.name == "renamed"


@pytest.mark.asyncio
async def test_delete_publishes_deleted_action():
    existing = _make_trigger()

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=existing)
    session.execute = AsyncMock(return_value=exec_result)
    session.delete = AsyncMock()
    session.commit = AsyncMock()

    with patch.object(trigger_service, "_publish_update", new=AsyncMock()) as pub:
        ok = await trigger_service.delete_trigger(session, existing.id)

    assert ok is True
    pub.assert_awaited_once_with("deleted", existing.id)


@pytest.mark.asyncio
async def test_reveal_secret_for_non_webhook_returns_none():
    existing = _make_trigger(type="watch", webhook_secret=None)

    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=existing)
    session.execute = AsyncMock(return_value=exec_result)

    result = await trigger_service.reveal_secret(session, existing.id)
    assert result is None


@pytest.mark.asyncio
async def test_create_cron_trigger_injects_derived_cron():
    session = AsyncMock(); session.add = MagicMock(); session.commit = AsyncMock(); session.refresh = AsyncMock()
    payload = TriggerCreate(
        name="Nightly", type="cron",
        config={"scan_path": "/shared/TV", "schedule": {"mode": "daily", "time": "03:00"}},
        action=ActionSchema(profile_name="P1", source_language=None,
                            target_language=None, skip_if_srt=True),
    )
    with patch.object(trigger_service, "_publish_update", new=AsyncMock()):
        t = await trigger_service.create_trigger(session, payload, profile_names={"P1"})
    assert t.config["cron"] == "0 3 * * *"


# ---------------------------------------------------------------------------
# WS5 (2026-07 audit): cron config validation at save time
# ---------------------------------------------------------------------------

def _mk_cron_trigger():
    return Trigger(
        id="t-cron", name="Nightly", type="cron",
        config={"schedule": {"mode": "daily", "time": "03:00"},
                "cron": "0 3 * * *", "scan_path": "/media"},
        action={"profile_name": "P1"}, file_filter=None, enabled=True,
        webhook_secret=None,
    )


@pytest.mark.asyncio
async def test_update_cron_config_without_schedule_preserves_cron():
    """A config update that omits 'schedule' must not silently store a config
    with no 'cron' key — that KeyError'd every evaluation, forever."""
    t = _mk_cron_trigger()
    session = AsyncMock(); session.commit = AsyncMock(); session.refresh = AsyncMock()
    from app.models.schemas import TriggerUpdate
    payload = TriggerUpdate(config={"scan_path": "/media/movies"})
    with patch("app.services.trigger_service.get_trigger", AsyncMock(return_value=t)), \
         patch("app.services.trigger_service._publish_update", AsyncMock()):
        out = await trigger_service.update_trigger(session, "t-cron", payload, {"P1"})
    assert out.config["cron"] == "0 3 * * *"
    assert out.config["scan_path"] == "/media/movies"


@pytest.mark.asyncio
async def test_update_cron_config_missing_scan_path_rejected():
    t = _mk_cron_trigger()
    session = AsyncMock(); session.commit = AsyncMock(); session.refresh = AsyncMock()
    from app.models.schemas import TriggerUpdate
    payload = TriggerUpdate(config={"schedule": {"mode": "daily", "time": "04:00"}})
    with patch("app.services.trigger_service.get_trigger", AsyncMock(return_value=t)), \
         patch("app.services.trigger_service._publish_update", AsyncMock()):
        with pytest.raises(ValueError, match="scan_path"):
            await trigger_service.update_trigger(session, "t-cron", payload, {"P1"})
