"""Tests for bodyless GET health endpoints:
  GET /api/v1/settings/jellyfin/health
  GET /api/v1/settings/transcription/health
Both read the persisted Settings row and delegate to the shared helpers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx


# ---------------------------------------------------------------------------
# Local copy of the session-mock helper (mirrors test_api_settings.py style)
# ---------------------------------------------------------------------------

def _mock_session_with_row(row):
    """Build a mock AsyncSessionLocal context manager that returns `row` from session.get()."""
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(return_value=row)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    mock_factory = MagicMock(return_value=mock_cm)
    return mock_factory, mock_session


# ---------------------------------------------------------------------------
# GET /api/v1/settings/jellyfin/health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_jellyfin_health_not_configured_no_row(client):
    """No Settings row → ok=False, detail contains 'configured' (case-insensitive)."""
    mock_factory, _ = _mock_session_with_row(None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings/jellyfin/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_jellyfin_health_not_configured_empty_fields(client, make_settings_row):
    """Settings row exists but jellyfin_url/api_key are empty → ok=False."""
    row = make_settings_row(jellyfin_url=None, jellyfin_api_key=None)
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings/jellyfin/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_jellyfin_health_success(client, make_settings_row):
    """Configured + upstream reachable → ok=True with version string."""
    row = make_settings_row(
        jellyfin_url="http://jellyfin.local",
        jellyfin_api_key="real-token",
    )
    mock_factory, _ = _mock_session_with_row(row)

    mock_response = MagicMock()
    mock_response.json.return_value = {"Version": "10.8.0"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.get("/api/v1/settings/jellyfin/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "10.8.0" in data["detail"]


@pytest.mark.asyncio
async def test_jellyfin_health_upstream_error(client, make_settings_row):
    """Configured + upstream raises → ok=False (error detail from exception)."""
    row = make_settings_row(
        jellyfin_url="http://jellyfin.local",
        jellyfin_api_key="real-token",
    )
    mock_factory, _ = _mock_session_with_row(row)

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.get("/api/v1/settings/jellyfin/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/settings/transcription/health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_transcription_health_not_configured_remote_no_url(client, make_settings_row):
    """remote-api backend with empty url → ok=False, detail contains 'configured'."""
    row = make_settings_row(
        transcription_backend="remote-api",
        transcription_api_url=None,
        transcription_model=None,
        transcription_api_key=None,
    )
    mock_factory, _ = _mock_session_with_row(row)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory):
        response = await client.get("/api/v1/settings/transcription/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert "configured" in data["detail"].lower()


@pytest.mark.asyncio
async def test_transcription_health_upstream_error_remote(client, make_settings_row):
    """remote-api + upstream connection error → ok=False."""
    row = make_settings_row(
        transcription_backend="remote-api",
        transcription_api_url="http://whisper.local",
        transcription_model="whisper-1",
        transcription_api_key="stored-key",
    )
    mock_factory, _ = _mock_session_with_row(row)

    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.get("/api/v1/settings/transcription/health")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False


@pytest.mark.asyncio
async def test_transcription_health_passes_persisted_key_unmasked(client, make_settings_row):
    """The DB key is passed straight through — not masked — to the helper.
    Verify by asserting the Authorization header carries the stored value."""
    stored_key = "stored-whisper-key"
    row = make_settings_row(
        transcription_backend="remote-api",
        transcription_api_url="http://whisper.local",
        transcription_model="whisper-1",
        transcription_api_key=stored_key,
    )
    mock_factory, _ = _mock_session_with_row(row)

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "hello"}
    mock_response.raise_for_status = MagicMock()
    mock_http_client = AsyncMock()
    mock_http_client.post = AsyncMock(return_value=mock_response)
    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_cm.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.settings.AsyncSessionLocal", mock_factory), \
         patch("app.api.settings.httpx.AsyncClient", return_value=mock_cm):
        response = await client.get("/api/v1/settings/transcription/health")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    _, call_kwargs = mock_http_client.post.call_args
    assert call_kwargs["headers"]["Authorization"] == f"Bearer {stored_key}"
