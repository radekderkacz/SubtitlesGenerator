"""Tests for the public webhook endpoint with Bearer auth."""
import hmac
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_webhook_200_on_valid_bearer(client):
    trig = MagicMock(
        id="t1", type="webhook", config={}, webhook_secret="s" * 64,
        action={"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "all", "value": None}
    )
    with (
        patch(
            "app.api.webhooks.trigger_service.get_trigger",
            new=AsyncMock(return_value=trig),
        ),
        patch(
            "app.api.webhooks.dispatch_event",
            new=AsyncMock(return_value="submitted"),
        ) as d,
    ):
        r = await client.post(
            "/api/v1/triggers/t1/webhook",
            json={"file_path": "/x.mkv"},
            headers={"Authorization": "Bearer " + "s" * 64},
        )
    assert r.status_code == 200
    d.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_401_on_bad_bearer(client):
    trig = MagicMock(id="t1", type="webhook", webhook_secret="s" * 64)
    with (
        patch(
            "app.api.webhooks.trigger_service.get_trigger",
            new=AsyncMock(return_value=trig),
        ),
        patch(
            "app.api.webhooks._record_auth_failure", new=AsyncMock()
        ) as rec,
    ):
        r = await client.post(
            "/api/v1/triggers/t1/webhook",
            json={"file_path": "/x.mkv"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert r.status_code == 401
    assert r.json()["code"] == "WEBHOOK_AUTH_FAILED"
    rec.assert_awaited_once()


@pytest.mark.asyncio
async def test_webhook_400_on_missing_file_path(client):
    trig = MagicMock(id="t1", type="webhook", webhook_secret="s" * 64)
    with (
        patch(
            "app.api.webhooks.trigger_service.get_trigger",
            new=AsyncMock(return_value=trig),
        ),
        patch("app.api.webhooks._record_missing_path", new=AsyncMock()),
    ):
        r = await client.post(
            "/api/v1/triggers/t1/webhook",
            json={"source": "sonarr"},
            headers={"Authorization": "Bearer " + "s" * 64},
        )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_404_unknown_trigger(client):
    with patch(
        "app.api.webhooks.trigger_service.get_trigger",
        new=AsyncMock(return_value=None),
    ):
        r = await client.post(
            "/api/v1/triggers/missing/webhook",
            json={"file_path": "/x.mkv"},
            headers={"Authorization": "Bearer x"},
        )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_record_auth_failure_adds_trigger_event():
    """_record_auth_failure should add a TriggerEvent row and commit."""
    from app.api.webhooks import _record_auth_failure
    from unittest.mock import AsyncMock as AM, MagicMock

    session = AM()
    session.add = MagicMock()
    session.commit = AM()
    await _record_auth_failure(session, "t1", "127.0.0.1")
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_record_missing_path_adds_trigger_event():
    """_record_missing_path should add a TriggerEvent row and commit."""
    from app.api.webhooks import _record_missing_path
    from unittest.mock import AsyncMock as AM, MagicMock

    session = AM()
    session.add = MagicMock()
    session.commit = AM()
    await _record_missing_path(session, "t1", {"source": "sonarr"}, "10.0.0.1")
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
