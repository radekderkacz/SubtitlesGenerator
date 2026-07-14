import asyncio
import io
import struct
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.core.security import ApiError, validate_nas_root_allowed
from app.models.orm import Settings
from app.models.schemas import (
    ListTranslationModelsRequest,
    ListTranslationModelsResponse,
    SettingsResponse,
    SettingsUpdate,
    TestConnectivityResponse,
    TestJellyfinRequest,
    TestTranscriptionRequest,
    TestTranslationModelRequest,
    TestTranslationModelResponse,
    TestTranslationRequest,
)

router = APIRouter()


def _is_system_configured(settings_row: Settings) -> bool:
    """First-run guard for the Queue page banner. The user has finished setup
    once they've picked a media library path (any non-empty value) AND
    configured a Whisper endpoint. `/media` is the conventional default
    and counts as configured if the volume mount actually exists."""
    media_ok = bool(settings_row.nas_mount_path)
    transcription_ok = bool(settings_row.transcription_api_url)
    return media_ok and transcription_ok


_CREDENTIAL_FIELDS = frozenset(
    ["jellyfin_api_key", "translation_api_key", "transcription_api_key", "hf_token"]
)

_NO_API_KEY_DETAIL = "API key not configured"

# Per-profile secrets inside the Settings.profiles JSON list — masked on GET
# and resolved from the stored row on PUT, exactly like the top-level fields
# (2026-07 audit R11: these leaked raw and could be overwritten with "***").
_PROFILE_CREDENTIAL_FIELDS = ("transcription_api_key", "translation_api_key")


def _masked_profiles(profiles: list | None) -> list | None:
    if not profiles:
        return profiles
    masked = []
    for profile in profiles:
        p = dict(profile)
        for field in _PROFILE_CREDENTIAL_FIELDS:
            p[field] = "***" if p.get(field) else None
        masked.append(p)
    return masked


def _mask_credentials(row: Settings) -> SettingsResponse:
    data = {
        col.name: getattr(row, col.name) for col in Settings.__table__.columns
    }
    for field in _CREDENTIAL_FIELDS:
        val = data.get(field)
        data[field] = "***" if val else None
    data["profiles"] = _masked_profiles(data.get("profiles"))
    return SettingsResponse.model_validate(data)


async def _resolve_masked_profile_keys(profiles: list) -> list:
    """Replace literal "***" placeholders in submitted profiles with the
    stored values (matched by profile name), so a client round-tripping a
    masked GET response can never store "***" as the actual key."""
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    stored = {p.get("name"): p for p in (row.profiles or [])} if row else {}
    resolved = []
    for profile in profiles:
        p = dict(profile)
        for field in _PROFILE_CREDENTIAL_FIELDS:
            if p.get(field) == "***":
                p[field] = (stored.get(p.get("name")) or {}).get(field)
        resolved.append(p)
    return resolved


async def _resolve_provider_api_key(
    payload_api_key: Optional[str], db_field: str
) -> str:
    """Resolve the effective provider key: a freshly-typed key wins
    (test-before-save); the ``"***"`` sentinel means "use the saved key"
    (DB lookup); empty/omitted means no key (e.g. keyless Ollama) and
    must NOT incur a DB read. Returns ``""`` when nothing is configured.

    Deliberately the inverse of the ``PUT /settings`` writer, which
    *drops* ``"***"`` so a save never clobbers the stored key — same
    sentinel, opposite semantics. The missing read side here is why
    masked keys never reached the provider → unauthenticated → 400."""
    key = payload_api_key or ""
    if not key:
        return ""
    if key != "***":
        return key
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    return (getattr(row, db_field, None) or "") if row else ""


def _silent_wav() -> bytes:
    sample_rate, n = 44100, 44100  # 1 second
    data = b'\x00\x00' * n
    buf = io.BytesIO()
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + len(data)))
    buf.write(b'WAVEfmt ')
    buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    buf.write(b'data')
    buf.write(struct.pack('<I', len(data)))
    buf.write(data)
    return buf.getvalue()


async def _check_jellyfin(url: str, api_key: str) -> TestConnectivityResponse:
    """Pure connectivity check against a Jellyfin server.

    Called by the POST ``/settings/test-jellyfin`` handler after credential
    resolution, and by the bodyless GET ``/settings/jellyfin/health`` endpoint
    (persisted settings).
    """
    if not url or not api_key:
        return TestConnectivityResponse(ok=False, detail="Not configured")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{url.rstrip('/')}/System/Info",
                headers={"X-Emby-Token": api_key},
            )
            response.raise_for_status()
            version = response.json().get("Version", "unknown")
            return TestConnectivityResponse(ok=True, detail=f"Connected — Jellyfin {version}")
    except Exception as e:
        return TestConnectivityResponse(ok=False, detail=str(e))


async def _check_transcription(
    url: str,
    model: str,
    api_key: str,
) -> TestConnectivityResponse:
    """Connectivity check for the OpenAI-compatible /v1/audio/transcriptions
    endpoint configured in Settings. Called by the POST
    ``/settings/test-transcription`` handler after credential resolution, and
    by the bodyless GET ``/settings/transcription/health`` endpoint.
    """
    if not url:
        return TestConnectivityResponse(ok=False, detail="Not configured")
    try:
        wav_bytes = _silent_wav()

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{url.rstrip('/')}/v1/audio/transcriptions",
                headers=headers,
                files={"file": ("test.wav", wav_bytes, "audio/wav")},
            )
            response.raise_for_status()
            return TestConnectivityResponse(ok=True, detail=f"Connected — {model}")
    except Exception as e:
        return TestConnectivityResponse(ok=False, detail=f"HTTP error or timeout: {str(e)}")


@router.get(
    "/settings",
    responses={
        200: {"description": "Current settings (credential fields masked)"},
        503: {"description": "Settings not initialized"},
    },
)
async def get_settings() -> SettingsResponse:
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="Settings not initialized",
        )
    return _mask_credentials(row)


def _validate_path_fields(update_dict: dict) -> JSONResponse | None:
    """Returns a 422 JSONResponse if any path field is missing/non-existent or
    outside the allowed mount-point prefixes; ``None`` when validation passes."""
    if "nas_mount_path" in update_dict:
        nas_path = update_dict["nas_mount_path"]
        if not nas_path or not Path(nas_path).is_dir():
            return JSONResponse(
                status_code=422,
                content={
                    "detail": (
                        f"NAS mount path '{nas_path}' does not exist inside the app container. "
                        "The library is mounted at /media — set this to /media."
                    ),
                    "code": "INVALID_NAS_PATH",
                },
            )
        try:
            validate_nas_root_allowed(nas_path)
        except ApiError as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail, "code": exc.code},
            )

    return None


@router.put(
    "/settings",
    responses={
        200: {"description": "Settings saved"},
        422: {"description": "Invalid NAS path"},
    },
)
async def put_settings(payload: SettingsUpdate, request: Request) -> JSONResponse:
    update_dict = payload.model_dump(exclude_unset=True)

    error_response = _validate_path_fields(update_dict)
    if error_response is not None:
        return error_response

    for field in _CREDENTIAL_FIELDS:
        if update_dict.get(field) == "***":
            del update_dict[field]

    if update_dict.get("profiles"):
        update_dict["profiles"] = await _resolve_masked_profile_keys(update_dict["profiles"])

    if not update_dict:
        return JSONResponse(content={"status": "ok"})

    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Settings)
            .values(id=1, **update_dict)
            .on_conflict_do_update(index_elements=["id"], set_=update_dict)
        )
        await session.execute(stmt)
        await session.commit()

    return JSONResponse(content={"status": "ok"})


@router.get(
    "/settings/jellyfin/health",
    responses={
        200: {"description": "Jellyfin connectivity (persisted settings)"},
    },
)
async def get_jellyfin_health() -> TestConnectivityResponse:
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    if row is None:
        return await _check_jellyfin("", "")
    return await _check_jellyfin(row.jellyfin_url or "", row.jellyfin_api_key or "")


@router.get(
    "/settings/transcription/health",
    responses={
        200: {"description": "Transcription backend connectivity (persisted settings)"},
    },
)
async def get_transcription_health() -> TestConnectivityResponse:
    async with AsyncSessionLocal() as session:
        row = await session.get(Settings, 1)
    if row is None:
        return await _check_transcription("", "", "")
    return await _check_transcription(
        row.transcription_api_url or "",
        row.transcription_model or "",
        row.transcription_api_key or "",
    )


@router.post(
    "/settings/test-transcription",
    responses={
        200: {"description": "Transcription backend connectivity result"},
    },
)
async def test_transcription(payload: TestTranscriptionRequest) -> TestConnectivityResponse:
    url = payload.url or ""
    model = payload.model or "whisper-1"
    api_key = await _resolve_provider_api_key(payload.api_key, "transcription_api_key")
    return await _check_transcription(url, model, api_key)


@router.post(
    "/settings/test-jellyfin",
    responses={
        200: {"description": "Jellyfin connectivity result"},
    },
)
async def test_jellyfin(payload: TestJellyfinRequest) -> TestConnectivityResponse:
    api_key = payload.api_key
    if api_key == "***":
        async with AsyncSessionLocal() as session:
            row = await session.get(Settings, 1)
        if not row or not row.jellyfin_api_key:
            return TestConnectivityResponse(ok=False, detail=_NO_API_KEY_DETAIL)
        api_key = row.jellyfin_api_key
    return await _check_jellyfin(payload.url, api_key)


@router.post(
    "/settings/test-translation",
    responses={
        200: {"description": "Translation backend connectivity result"},
    },
)
async def test_translation(payload: TestTranslationRequest) -> TestConnectivityResponse:
    provider = payload.provider
    url = payload.url or ""
    model = payload.model or ""
    api_key = await _resolve_provider_api_key(payload.api_key, "translation_api_key")
    if not api_key and provider in _CLOUD_PROVIDERS:
        return TestConnectivityResponse(ok=False, detail=_NO_API_KEY_DETAIL)

    # Use the shared resolver instead of a parallel switch — the
    # previous duplicated copy had Google pinned to /v1/chat/completions
    # (404; Google's OpenAI-compat shim lives at /v1beta/openai/chat/
    # completions) and the duplication is what let that drift go
    # unnoticed for weeks. One source of truth is the only way to keep
    # this in sync.
    endpoint = _translation_endpoint(provider, url)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
    }

    # 60s — Ollama cold-loads a 9-35B model on first call, which can easily
    # take 25-50s. The shorter 15s used elsewhere causes "Test Connection"
    # to fail spuriously the first time after a model swap.
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(endpoint, headers=headers, json=body)
            response.raise_for_status()
            return TestConnectivityResponse(ok=True, detail="Connected")
    except httpx.HTTPStatusError as e:
        # Surface the upstream API's error message instead of just the
        # status code. Without this the user sees "400 Bad Request" and
        # has no idea WHY — but the response body almost always names
        # the actual problem (e.g. ``"model 'gemma3:27b' not found"``
        # when a user picks Google with a stale Ollama model name still
        # in the field, 2026-05-15 bug).
        return TestConnectivityResponse(
            ok=False,
            detail=_summarise_upstream_error(e, provider, model),
        )
    except Exception as e:
        return TestConnectivityResponse(ok=False, detail=str(e))


def _extract_upstream_error_message(response: "httpx.Response") -> str:
    """Pull ``error.message`` (OpenAI/Google/OpenRouter shape) or
    ``message`` from a JSON error body. Returns ``""`` if the body
    isn't JSON or has no recognisable message field."""
    try:
        data = response.json()
    except Exception:  # body not JSON or already drained
        return ""
    if not isinstance(data, dict):
        return ""
    err = data.get("error")
    if isinstance(err, dict):
        msg = str(err.get("message") or "").strip()
        if msg:
            return msg
    elif isinstance(err, str):
        msg = err.strip()
        if msg:
            return msg
    return str(data.get("message") or "").strip()


_CLOUD_PROVIDERS = ("google", "openai", "openrouter")


def _summarise_upstream_error(
    exc: httpx.HTTPStatusError, provider: str, model: str
) -> str:
    """Pull the most actionable string out of an upstream API's 4xx/5xx
    response body and prepend the status. Adds a one-line hint when a
    colon-shaped Ollama-style model id is sent to a cloud provider —
    the 2026-05-15 bug class (e.g. ``gemma3:27b`` against Google's API
    returns 400 ``"models/gemma3:27b is not a known Gemini model"``)."""
    status = exc.response.status_code
    upstream_message = _extract_upstream_error_message(exc.response)
    detail = f"{status} {exc.response.reason_phrase or 'error'}"
    if upstream_message:
        detail = f"{detail}: {upstream_message}"
    # The colon in `name:tag` is a strong tell for an Ollama id; cloud
    # providers reject these as 400/404 — the only window where the hint
    # is actionable.
    looks_like_ollama_id = bool(model) and ":" in model
    if status in (400, 404) and provider in _CLOUD_PROVIDERS and looks_like_ollama_id:
        detail += (
            f" — '{model}' looks like an Ollama model id but provider is "
            f"'{provider}'. Pick a {provider}-compatible model name."
        )
    return detail


def _translation_endpoint(provider: str, url: str) -> str:
    """Resolve the OpenAI-compatible chat-completions URL for a provider.
    Shared by ``test_translation`` (1-token ping) and
    ``test_translation_model`` (real probes) so the routing logic only
    lives in one place."""
    if provider == "openai":
        return "https://api.openai.com/v1/chat/completions"
    if provider == "google":
        return "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1/chat/completions"
    if provider == "custom":
        return url
    # ollama + future OpenAI-compatible providers
    return f"{url.rstrip('/')}/v1/chat/completions"


# Fixed probe content — versioned by design. The user reads the response
# message + the sample translation and can judge "is this model good
# enough for my content?" without running a real job. Changing these
# strings later will reset the expected outputs in the API tests too.

_PROBE_SOURCE = (
    "Tell me one thing before you leave. How did I die when I was just shot? "
    "We could have escaped, but I had us go back for Spider."
)
# Names the model must preserve verbatim (or recognisably-declined) in the
# translation output. Lowercased substring match; if any match we consider
# the proper-noun check passed.
_PROBE_PROPER_NOUNS = ("spider",)

# Compact transcript synthesised from common subtitle patterns + 13 well-
# known Avatar 3 proper nouns. Small enough that even modest models follow
# the JSON contract (test 1 in the gemma3/aya comparison) but large enough
# to surface long-context format collapse (where aya replied in prose).
_PROBE_TRANSCRIPT = "\n".join(
    [
        "Get back here now.",
        "I love you, brother.",
        "Spider, get back!",
        "We have to keep moving.",
        "Where is Neytiri?",
        "Hold the line.",
        "Pull back!",
        "Jake is in danger.",
        "Stay close to me.",
        "What happened to your face?",
        "We need to find them.",
        "Pandora is alive.",
        "The Na'vi will fight.",
        "RDA is coming.",
        "Unobtainium is still the goal.",
        "Lo'ak, hide!",
        "Kiri, stay close.",
        "Tuk, are you ok?",
        "Quaritch is hunting us.",
        "AMP suits incoming.",
        "Hell's Gate is locked down.",
    ]
)


def _glossary_extraction_prompts(transcript: str) -> tuple[str, str]:
    """Return the same (system, user) pair the worker uses for glossary
    extraction. Kept here as a local copy rather than imported from
    ``app.worker.translation_prompts`` to avoid pulling Celery/worker
    deps into the API layer at import time. If you change the prompt
    in the worker, mirror it here so the Test-this-model button
    reflects production behaviour."""
    system = (
        "You extract proper nouns from film subtitle transcripts so they can "
        "be preserved verbatim during translation. Return ONLY a JSON array "
        "of strings — no commentary, no markdown, no surrounding object."
    )
    user = (
        "Extract every proper noun from this transcript that should NOT be "
        "translated to another language. Include:\n"
        "- Character names and nicknames (Jake, Spider, Neytiri)\n"
        "- Place names (Pandora, Hell's Gate)\n"
        "- Fictional species / factions (Na'vi, RDA)\n"
        "- Made-up or technical terms (unobtainium, AMP suit)\n"
        "- Brand names\n\n"
        "Skip ordinary words even if capitalised at sentence start. Skip "
        "names of real-world places that have established target-language "
        "translations (e.g. London → Londyn in Polish).\n\n"
        "Output format: a JSON array of strings, deduplicated, in the case "
        "the term appears in the transcript. Example: "
        '["Jake", "Spider", "Pandora", "Na\'vi"]\n\n'
        "Transcript:\n" + transcript
    )
    return system, user


def _parse_glossary_response(raw: str) -> Optional[list[str]]:
    """Mirror of the worker's tolerant parser. Returns ``None`` when the
    response can't be coerced to a JSON array (which is itself a
    diagnostic — that exact case is what made aya unsuitable on
    2026-05-15)."""
    import json as _json

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1] if "```" in cleaned[3:] else cleaned[3:]
        if cleaned.startswith("json\n"):
            cleaned = cleaned[5:]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        parsed = _json.loads(cleaned[start:end + 1])
    except _json.JSONDecodeError:
        return None
    if not isinstance(parsed, list):
        return None
    out: list[str] = []
    seen: set[str] = set()
    for item in parsed:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


async def _run_translation_probe(
    endpoint: str, headers: dict[str, str], model: str, target_language: str
) -> tuple[Optional[str], Optional[float], Optional[bool], Optional[str]]:
    """Probe 1: translation + Spider-preservation. Returns
    (sample_translation, sec_per_segment, preserves_proper_nouns,
    error_detail). On success error_detail is None; on network/HTTP
    failure the first three values are None and error_detail carries a
    short diagnostic."""
    import time

    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a film subtitle translator. Output ONLY the translated line "
                    f"in {target_language}, no commentary. Preserve proper nouns "
                    "like character names exactly — declined to target-language grammar "
                    "is fine, fully translating the name (e.g. 'Spider' → 'pająk') is not."
                ),
            },
            {"role": "user", "content": _PROBE_SOURCE},
        ],
    }
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return None, None, None, f"Translation probe failed: {type(e).__name__}: {e}"
    sample = (data["choices"][0]["message"]["content"] or "").strip()
    sec = time.time() - t0
    preserved = any(name in sample.lower() for name in _PROBE_PROPER_NOUNS)
    return sample, sec, preserved, None


async def _run_glossary_probe(
    endpoint: str, headers: dict[str, str], model: str
) -> tuple[Optional[list[str]], bool]:
    """Probe 2: glossary extraction. Returns
    (sample_glossary, glossary_json_valid). Failures (network, parse,
    refused) are non-fatal — the caller still reports the translation
    probe's verdict — so we collapse all failure modes to (None, False)."""
    system, user = _glossary_extraction_prompts(_PROBE_TRANSCRIPT)
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = await client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None, False
    raw = (data["choices"][0]["message"]["content"] or "").strip()
    parsed = _parse_glossary_response(raw)
    return parsed, parsed is not None and len(parsed) >= 3


def _format_probe_detail(
    preserves_proper_nouns: Optional[bool],
    glossary_json_valid: Optional[bool],
    sample_glossary: Optional[list[str]],
    sec_per_segment: Optional[float],
) -> str:
    parts = [
        "Proper nouns preserved" if preserves_proper_nouns else "Proper nouns NOT preserved",
        (
            f"glossary returned {len(sample_glossary or [])} terms as valid JSON"
            if glossary_json_valid
            else "glossary extraction did not return a valid JSON array"
        ),
    ]
    if sec_per_segment is not None:
        parts.append(f"{sec_per_segment:.1f}s per cue (warm)")
    return "; ".join(parts)


@router.post(
    "/settings/test-translation-model",
    responses={200: {"description": "Translation-model probe result"}},
)
async def test_translation_model(
    payload: TestTranslationModelRequest,
) -> TestTranslationModelResponse:
    """Run the two probes that surfaced the gemma3/aya quality gap on
    2026-05-15 — a Spider-preservation translation and a glossary
    extraction. Each probe is delegated to a helper so this endpoint
    function stays under SonarQube's cognitive-complexity threshold."""
    endpoint = _translation_endpoint(payload.provider, payload.url or "")
    api_key = await _resolve_provider_api_key(payload.api_key, "translation_api_key")
    if not api_key and payload.provider in _CLOUD_PROVIDERS:
        return TestTranslationModelResponse(ok=False, detail=_NO_API_KEY_DETAIL)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    sample_translation, sec_per_segment, preserves_proper_nouns, err = (
        await _run_translation_probe(
            endpoint, headers, payload.model or "", payload.target_language
        )
    )
    if err is not None:
        return TestTranslationModelResponse(ok=False, detail=err)

    sample_glossary, glossary_json_valid = await _run_glossary_probe(
        endpoint, headers, payload.model or ""
    )

    overall_ok = bool(preserves_proper_nouns and glossary_json_valid)
    return TestTranslationModelResponse(
        ok=overall_ok,
        preserves_proper_nouns=preserves_proper_nouns,
        glossary_json_valid=glossary_json_valid,
        sec_per_segment=sec_per_segment,
        sample_translation=sample_translation,
        sample_glossary=sample_glossary,
        detail=_format_probe_detail(
            preserves_proper_nouns,
            glossary_json_valid,
            sample_glossary,
            sec_per_segment,
        ),
    )


def _models_endpoint(provider: str, url: str) -> Optional[str]:
    if provider == "openai":
        return "https://api.openai.com/v1/models"
    if provider == "openrouter":
        # OpenRouter exposes the standard OpenAI-compatible model index
        # at api.openrouter.ai/api/v1/models (no auth required for the
        # public catalogue).
        return "https://openrouter.ai/api/v1/models"
    if provider == "google":
        # Google's OpenAI compatibility shim DOES include /models — same
        # base URL as the chat-completions endpoint, just /models on the
        # end. Auth via the same Bearer token. (Earlier comment claimed
        # otherwise — that was wrong, fixed 2026-05-15.)
        return "https://generativelanguage.googleapis.com/v1beta/openai/models"
    if provider in {"ollama", "custom"} and url:
        # Strip a trailing /v1 too — users often paste base URLs that already
        # include it (e.g. ``http://host:11434/v1``).
        base = url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        return f"{base}/v1/models"
    return None


@router.post(
    "/settings/list-translation-models",
    responses={
        200: {
            "description": "Models discovered at the provider's /v1/models "
            "endpoint, or an empty list with a `detail` explaining why."
        },
    },
)
async def list_translation_models(
    payload: ListTranslationModelsRequest,
) -> ListTranslationModelsResponse:
    """Calls the provider's OpenAI-compatible /v1/models endpoint so the UI
    can populate a real model dropdown instead of asking the user to type a
    name from memory. Failures return ``models=[]`` + a ``detail`` string —
    the UI falls back to a free-text input in that case."""
    endpoint = _models_endpoint(payload.provider, payload.url or "")
    if endpoint is None:
        return ListTranslationModelsResponse(
            models=[],
            detail=f"Listing not supported for provider '{payload.provider}'",
        )

    api_key = await _resolve_provider_api_key(payload.api_key, "translation_api_key")
    if not api_key and payload.provider in _CLOUD_PROVIDERS:
        return ListTranslationModelsResponse(
            models=[], detail=_NO_API_KEY_DETAIL
        )
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(endpoint, headers=headers)
            response.raise_for_status()
            data = response.json()
            ids = sorted(
                {m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m}
            )
            return ListTranslationModelsResponse(models=ids)
    except Exception as e:
        return ListTranslationModelsResponse(models=[], detail=str(e)[:200])
