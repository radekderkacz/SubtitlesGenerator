import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_health_ok(client):
    """Health endpoint returns 200 with all services ok when DB and Redis respond."""
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("app.main.AsyncSessionLocal") as mock_session_factory, \
         patch("app.main.aioredis.from_url", return_value=mock_redis):

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_cm

        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["db"] == "ok"
    assert data["redis"] == "ok"


@pytest.mark.asyncio
async def test_health_db_down(client):
    """Health endpoint returns 503 with db=error when DB is unavailable."""
    mock_redis = AsyncMock()
    mock_redis.ping = AsyncMock()
    mock_redis.aclose = AsyncMock()

    with patch("app.main.AsyncSessionLocal") as mock_session_factory, \
         patch("app.main.aioredis.from_url", return_value=mock_redis):

        mock_cm = AsyncMock()
        mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
        mock_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session_factory.return_value = mock_cm

        response = await client.get("/api/v1/health")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db"] == "error"
