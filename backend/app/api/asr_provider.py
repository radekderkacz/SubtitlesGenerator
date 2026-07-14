"""Whisper-ASR-webservice-compatible endpoints (Bazarr's "whisper" provider).

Bazarr (and anything else speaking the ahmetoner/whisper-asr-webservice
protocol) can point at SubtitlesGen as its Whisper provider:

    POST /asr?task=transcribe&language=xx&output=srt   (audio in the body)
    POST /detect-language                              (audio in the body)

The audio is forwarded to the transcription backend of the DEFAULT profile
(first in Settings → Profiles; override with ?profile=<name>), and the
result runs through the same speech-aligned cue pipeline as native jobs —
so Bazarr gets the identical subtitle quality.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import uuid

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.database import AsyncSessionLocal
from app.models.orm import Settings

router = APIRouter()

_MAX_AUDIO_BYTES = 200 * 1024 * 1024


async def _profile_backend(profile_name: str | None) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    profiles = (row.profiles or []) if row else []
    if not profiles:
        return None
    if profile_name:
        return next((p for p in profiles if p.get("name") == profile_name), None)
    return profiles[0]


def _spool_and_transcribe(body: bytes, backend: dict, language: str | None) -> dict:
    """Blocking half of the upload flow: spool the audio to a temp file, run
    the transcription, clean up. Runs in a thread so the event loop never
    touches the filesystem."""
    tmp_path = os.path.join(tempfile.gettempdir(), f"asr-{uuid.uuid4()}.audio")
    try:
        with open(tmp_path, "wb") as f:
            f.write(body)
        return _transcribe_upload(tmp_path, backend, language)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def _transcribe_body(body: bytes, backend: dict, language: str | None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _spool_and_transcribe, body, backend, language)


def _transcribe_upload(path: str, backend: dict, language: str | None) -> dict:
    from app.worker.asr_filters import filter_segments, normalize_lang_code
    from app.worker.tasks import _run_transcription_remote_blocking

    hint = normalize_lang_code(language) if language and language != "auto" else None
    result = _run_transcription_remote_blocking(
        path,
        backend.get("transcription_api_url") or "",
        backend.get("transcription_model") or "large-v3",
        backend.get("transcription_api_key"),
        language_hint=hint,
    )
    filtered = filter_segments(result.get("segments") or [])
    result["segments"] = filtered.segments
    return result


@router.post(
    "/asr",
    responses={
        200: {"description": "SRT (or text) subtitle content"},
        422: {"description": "No transcription profile configured"},
        413: {"description": "Audio too large"},
    },
)
async def asr(
    request: Request,
    task: Annotated[str, Query()] = "transcribe",
    language: Annotated[str | None, Query()] = None,
    output: Annotated[str, Query()] = "srt",
    profile: Annotated[str | None, Query()] = None,
):
    """whisper-asr-webservice-compatible transcription: audio in, SRT out."""
    from app.worker.tasks import _segments_to_srt, build_source_cues

    backend = await _profile_backend(profile)
    if not backend or not backend.get("transcription_api_url"):
        return JSONResponse(status_code=422, content={
            "detail": "No transcription profile configured", "code": "NO_PROFILE"})

    body = await request.body()
    if len(body) > _MAX_AUDIO_BYTES:
        return JSONResponse(status_code=413, content={
            "detail": "audio too large", "code": "AUDIO_TOO_LARGE"})
    if not body:
        return JSONResponse(status_code=400, content={
            "detail": "empty audio body", "code": "EMPTY_BODY"})

    result = await _transcribe_body(body, backend, language)

    cues = build_source_cues(result)
    if output == "srt":
        return PlainTextResponse(_segments_to_srt(cues), media_type="text/plain")
    return PlainTextResponse(
        "\n".join(" ".join(c["text"].splitlines()) for c in cues),
        media_type="text/plain",
    )


@router.post(
    "/detect-language",
    responses={
        200: {"description": "Detected language name + code"},
        422: {"description": "No transcription profile configured"},
    },
)
async def detect_language_endpoint(
    request: Request,
    profile: Annotated[str | None, Query()] = None,
):
    """whisper-asr-webservice-compatible language detection."""
    from app.worker.asr_filters import normalize_lang_code
    from app.worker.translation_prompts import language_name

    backend = await _profile_backend(profile)
    if not backend or not backend.get("transcription_api_url"):
        return JSONResponse(status_code=422, content={
            "detail": "No transcription profile configured", "code": "NO_PROFILE"})
    body = await request.body()
    if not body:
        return JSONResponse(status_code=400, content={
            "detail": "empty audio body", "code": "EMPTY_BODY"})

    result = await _transcribe_body(body, backend, None)
    code = normalize_lang_code(result.get("language"))
    return {"detected_language": language_name(code).lower() or code,
            "language_code": code}
