"""HTTP tests for /api/v1/triggers CRUD endpoints."""
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone


def _fake_trigger(tid="t1", name="TV", ttype="watch"):
    now = datetime.now(timezone.utc)
    return type(
        "T",
        (),
        {
            "id": tid,
            "name": name,
            "type": ttype,
            "config": {"path": "/shared/TV"},
            "action": {
                "profile_name": "P1",
                "source_language": None,
                "target_language": None,
                "skip_if_srt": True,
            },
            "file_filter": {"type": "all", "value": None},
            "enabled": True,
            "webhook_secret": None,
            "created_at": now,
            "updated_at": now,
        },
    )()


@pytest.mark.asyncio
async def test_post_triggers_creates_watch(client):
    payload = {
        "name": "TV",
        "type": "watch",
        "config": {"path": "/shared/TV"},
        "action": {
            "profile_name": "P1",
            "source_language": None,
            "target_language": None,
            "skip_if_srt": True,
        },
        "file_filter": {"type": "all", "value": None},
    }
    fake = _fake_trigger()
    with (
        patch(
            "app.api.triggers.trigger_service.create_trigger",
            new=AsyncMock(return_value=fake),
        ),
        patch(
            "app.api.triggers._profile_names",
            new=AsyncMock(return_value={"P1"}),
        ),
        patch(
            "app.api.triggers.trigger_service._derive_stats",
            new=AsyncMock(return_value=(None, 0)),
        ),
    ):
        resp = await client.post("/api/v1/triggers", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "TV"
    assert body["action"]["profile_name"] == "P1"
    assert "webhook_secret" not in body  # secret never in normal response


@pytest.mark.asyncio
async def test_get_triggers_empty(client):
    with (
        patch(
            "app.api.triggers.trigger_service.list_triggers",
            new=AsyncMock(return_value=[]),
        ),
    ):
        resp = await client.get("/api/v1/triggers")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_trigger_not_found(client):
    with patch(
        "app.api.triggers.trigger_service.get_trigger",
        new=AsyncMock(return_value=None),
    ):
        resp = await client.get("/api/v1/triggers/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_trigger_not_found(client):
    with patch(
        "app.api.triggers.trigger_service.delete_trigger",
        new=AsyncMock(return_value=False),
    ):
        resp = await client.delete("/api/v1/triggers/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fire_webhook_trigger_returns_400(client):
    trig = MagicMock(id="t1", type="webhook")
    with patch(
        "app.api.triggers.trigger_service.get_trigger",
        new=AsyncMock(return_value=trig),
    ):
        r = await client.post("/api/v1/triggers/t1/fire")
    assert r.status_code == 400
    assert r.json()["code"] == "MANUAL_FIRE_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_fire_watch_trigger_scans_and_dispatches(monkeypatch, client):
    trig = MagicMock(id="t1", type="watch", config={"path": "/scan"},
                     action={"profile_name": "P1"}, file_filter=None)
    monkeypatch.setattr("os.walk", lambda p: [(p, [], ["a.mkv"])])
    with (
        patch(
            "app.api.triggers.trigger_service.get_trigger",
            new=AsyncMock(return_value=trig),
        ),
        patch("app.api.triggers.dispatch_event", new=AsyncMock()) as d,
    ):
        r = await client.post("/api/v1/triggers/t1/fire")
    assert r.status_code == 200
    d.assert_awaited_once()


@pytest.mark.asyncio
async def test_fire_trigger_not_found(client):
    with patch(
        "app.api.triggers.trigger_service.get_trigger",
        new=AsyncMock(return_value=None),
    ):
        r = await client.post("/api/v1/triggers/missing/fire")
    assert r.status_code == 404
    assert r.json()["code"] == "TRIGGER_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_trigger_events_filtered_by_outcome(client):
    from app.models.orm import TriggerEvent
    from datetime import datetime, timezone
    fake_event = TriggerEvent(
        id="e1",
        trigger_id="t1",
        fired_at=datetime.now(timezone.utc),
        event_payload={},
        outcome="submitted",
        job_id=None,
        error_message=None,
    )
    with patch(
        "app.api.triggers.trigger_service",
    ):
        # Mock session.execute to return the event
        from app.main import app
        from app.core.database import get_db
        from sqlalchemy.ext.asyncio import AsyncSession
        from unittest.mock import AsyncMock as AM

        mock_session = AM(spec=AsyncSession)
        result = MagicMock()
        result.scalars.return_value.all.return_value = [fake_event]
        mock_session.execute = AM(return_value=result)

        app.dependency_overrides[get_db] = lambda: mock_session
        r = await client.get("/api/v1/triggers/events?outcome=submitted&limit=10")
    app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_post_triggers_profile_not_found_returns_422(client):
    with (
        patch(
            "app.api.triggers._profile_names",
            new=AsyncMock(return_value={"Other"}),
        ),
        patch(
            "app.api.triggers.trigger_service.create_trigger",
            new=AsyncMock(
                side_effect=__import__(
                    "app.services.trigger_service", fromlist=["ProfileNotFoundError"]
                ).ProfileNotFoundError("P1 not found")
            ),
        ),
    ):
        resp = await client.post(
            "/api/v1/triggers",
            json={
                "name": "TV",
                "type": "watch",
                "config": {"path": "/shared/TV"},
                "action": {"profile_name": "P1", "source_language": None,
                           "target_language": None, "skip_if_srt": True},
            },
        )
    assert resp.status_code == 422
    assert resp.json()["code"] == "PROFILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_trigger_not_found(client):
    with (
        patch(
            "app.api.triggers._profile_names",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.triggers.trigger_service.update_trigger",
            new=AsyncMock(return_value=None),
        ),
    ):
        r = await client.patch(
            "/api/v1/triggers/nonexistent",
            json={"name": "New Name"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_trigger_profile_not_found(client):
    with (
        patch(
            "app.api.triggers._profile_names",
            new=AsyncMock(return_value=set()),
        ),
        patch(
            "app.api.triggers.trigger_service.update_trigger",
            new=AsyncMock(
                side_effect=__import__(
                    "app.services.trigger_service", fromlist=["ProfileNotFoundError"]
                ).ProfileNotFoundError("P2 not found")
            ),
        ),
    ):
        r = await client.patch(
            "/api/v1/triggers/t1",
            json={"name": "New"},
        )
    assert r.status_code == 422
    assert r.json()["code"] == "PROFILE_NOT_FOUND"


@pytest.mark.asyncio
async def test_delete_trigger_success(client):
    with patch(
        "app.api.triggers.trigger_service.delete_trigger",
        new=AsyncMock(return_value=True),
    ):
        r = await client.delete("/api/v1/triggers/t1")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_reveal_secret_returns_secret(client):
    with patch(
        "app.api.triggers.trigger_service.reveal_secret",
        new=AsyncMock(return_value="abc123"),
    ):
        r = await client.get("/api/v1/triggers/t1/secret")
    assert r.status_code == 200
    assert r.json()["webhook_secret"] == "abc123"


@pytest.mark.asyncio
async def test_reveal_secret_non_webhook_trigger(client):
    non_wh = _fake_trigger(ttype="watch")
    with (
        patch(
            "app.api.triggers.trigger_service.reveal_secret",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.api.triggers.trigger_service.get_trigger",
            new=AsyncMock(return_value=non_wh),
        ),
    ):
        r = await client.get("/api/v1/triggers/t1/secret")
    assert r.status_code == 400
    assert r.json()["code"] == "NOT_A_WEBHOOK_TRIGGER"


@pytest.mark.asyncio
async def test_reveal_secret_trigger_not_found(client):
    with (
        patch(
            "app.api.triggers.trigger_service.reveal_secret",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "app.api.triggers.trigger_service.get_trigger",
            new=AsyncMock(return_value=None),
        ),
    ):
        r = await client.get("/api/v1/triggers/missing/secret")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_cron_preview_accepts_schedule_object(client):
    r = await client.post("/api/v1/triggers/cron/preview",
        json={"schedule": {"mode": "daily", "time": "03:00"}, "count": 3})
    assert r.status_code == 200
    body = r.json()
    assert len(body["next_fires"]) == 3


@pytest.mark.asyncio
async def test_preview_cron_invalid_schedule_mode(client):
    r = await client.post(
        "/api/v1/triggers/cron/preview",
        json={"schedule": {"mode": "yearly"}, "count": 2},
    )
    assert r.status_code == 422
