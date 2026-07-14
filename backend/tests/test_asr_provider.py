"""Bazarr whisper-provider endpoints (WS15, 2026-07 audit)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.main import app


def _settings_with_profile():
    row = MagicMock()
    row.profiles = [{"name": "P1", "transcription_api_url": "http://whisper.test/v1",
                     "transcription_model": "large-v3", "transcription_api_key": None}]
    return row


def _session_ctx(row):
    session = AsyncMock()
    session.get = AsyncMock(return_value=row)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=cm)


@pytest.mark.asyncio
async def test_asr_returns_srt(client):
    result = {"language": "en",
              "segments": [{"start": 0.0, "end": 2.5, "text": "Hello there, friend."}],
              "words": []}
    with patch("app.api.asr_provider.AsyncSessionLocal",
               _session_ctx(_settings_with_profile())), \
         patch("app.worker.tasks._run_transcription_remote_blocking",
               return_value=result):
        r = await client.post("/asr?task=transcribe&language=en&output=srt",
                              content=b"RIFFfakeaudio")
    assert r.status_code == 200
    assert "-->" in r.text
    assert "Hello there, friend." in r.text


@pytest.mark.asyncio
async def test_asr_422_without_profile(client):
    row = MagicMock(); row.profiles = []
    with patch("app.api.asr_provider.AsyncSessionLocal", _session_ctx(row)):
        r = await client.post("/asr", content=b"x")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_asr_400_on_empty_body(client):
    with patch("app.api.asr_provider.AsyncSessionLocal",
               _session_ctx(_settings_with_profile())):
        r = await client.post("/asr", content=b"")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_detect_language_shape(client):
    result = {"language": "english", "segments": [
        {"start": 0.0, "end": 1.0, "text": "Hi."}], "words": []}
    with patch("app.api.asr_provider.AsyncSessionLocal",
               _session_ctx(_settings_with_profile())), \
         patch("app.worker.tasks._run_transcription_remote_blocking",
               return_value=result):
        r = await client.post("/detect-language", content=b"RIFFfake")
    assert r.status_code == 200
    body = r.json()
    assert body["language_code"] == "en"
    assert body["detected_language"] == "english"
