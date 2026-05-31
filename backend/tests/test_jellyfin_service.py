"""Jellyfin library refresh service.

Covers the five acceptance criteria for the service layer; worker-side
integration is exercised in test_worker_tasks.py via a stub.
"""
from datetime import datetime, timezone

import httpx
import pytest

from app.models.orm import Settings
from app.services.jellyfin import (
    JellyfinNotConfigured,
    JellyfinRefreshError,
    trigger_library_scan,
    trigger_library_scan_safe,
)


def _settings(**overrides) -> Settings:
    now = datetime.now(timezone.utc)
    return Settings(
        id=1,
        nas_mount_path="/media",
        jellyfin_url=overrides.pop("jellyfin_url", "http://jellyfin.local"),
        jellyfin_api_key=overrides.pop("jellyfin_api_key", "secret-key"),
        created_at=now,
        updated_at=now,
        **overrides,
    )


# ---------------------------------------------------------------------------
# trigger_library_scan — direct service path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trigger_sends_post_to_library_refresh_with_emby_token():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await trigger_library_scan(_settings(), client=client)

    assert captured["method"] == "POST"
    assert captured["url"] == "http://jellyfin.local/Library/Refresh"
    assert captured["headers"]["x-emby-token"] == "secret-key"


@pytest.mark.asyncio
async def test_trigger_strips_trailing_slash_from_url():
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await trigger_library_scan(_settings(jellyfin_url="http://jf.local/"), client=client)

    assert seen == ["http://jf.local/Library/Refresh"]


@pytest.mark.asyncio
async def test_trigger_raises_not_configured_when_url_missing():
    with pytest.raises(JellyfinNotConfigured):
        await trigger_library_scan(_settings(jellyfin_url=None))


@pytest.mark.asyncio
async def test_trigger_raises_not_configured_when_api_key_missing():
    with pytest.raises(JellyfinNotConfigured):
        await trigger_library_scan(_settings(jellyfin_api_key=None))


@pytest.mark.asyncio
async def test_trigger_raises_refresh_error_on_non_2xx():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JellyfinRefreshError) as exc:
            await trigger_library_scan(_settings(), client=client)
    assert "503" in str(exc.value)


@pytest.mark.asyncio
async def test_trigger_raises_refresh_error_on_request_failure():
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(JellyfinRefreshError) as exc:
            await trigger_library_scan(_settings(), client=client)
    assert "connection refused" in str(exc.value)


# ---------------------------------------------------------------------------
# trigger_library_scan_safe — wrapper used by the worker
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_returns_true_on_success(monkeypatch):
    async def fake_scan(*_args, **_kwargs):
        return None

    monkeypatch.setattr("app.services.jellyfin.trigger_library_scan", fake_scan)
    assert await trigger_library_scan_safe(_settings()) is True


@pytest.mark.asyncio
async def test_safe_returns_false_when_not_configured(monkeypatch):
    async def fake_scan(*_args, **_kwargs):
        raise JellyfinNotConfigured()

    monkeypatch.setattr("app.services.jellyfin.trigger_library_scan", fake_scan)
    assert await trigger_library_scan_safe(_settings()) is False


@pytest.mark.asyncio
async def test_safe_returns_false_on_refresh_error(monkeypatch, caplog):
    async def fake_scan(*_args, **_kwargs):
        raise JellyfinRefreshError("Jellyfin returned HTTP 502")

    monkeypatch.setattr("app.services.jellyfin.trigger_library_scan", fake_scan)
    with caplog.at_level("WARNING"):
        assert await trigger_library_scan_safe(_settings()) is False
    assert any("Jellyfin library refresh failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_safe_does_not_log_credentials(monkeypatch, caplog):
    async def fake_scan(*_args, **_kwargs):
        raise JellyfinRefreshError("Jellyfin returned HTTP 401")

    monkeypatch.setattr("app.services.jellyfin.trigger_library_scan", fake_scan)
    with caplog.at_level("DEBUG"):
        await trigger_library_scan_safe(_settings(jellyfin_api_key="super-secret-token"))
    for record in caplog.records:
        assert "super-secret-token" not in record.message
