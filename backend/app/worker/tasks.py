import asyncio
import json
import math
import os
import time
from datetime import datetime, timezone

import httpx

import redis.asyncio as aioredis

from app.core.config import app_settings
from app.models.orm import Job, Settings, _utcnow
from app.models.schemas import JobStatus, JobPhase
from app.worker.celery_app import celery_app
from app.worker.usage import UsageAccumulator, extract_usage

from app.services.job_events import REDIS_CHANNEL as _REDIS_CHANNEL, build_job_event_payload

# Per-job logs live at the docker-compose mount point inside the worker
# container (host: ./data/logs ↔ container: /app/logs). Previously this
# was "./data/logs" which resolves to /app/data/logs from the worker's
# CWD — that path isn't mounted, so logs were trapped inside the
# container and invisible from the deploy host.
_LOG_DIR = "/app/logs"

def _write_log(log_path: str, level: str, job_id: str, message: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} {level:<5} [job:{job_id}] {message}\n"
    with open(log_path, "a") as f:
        f.write(line)


async def _fetch_settings() -> Settings:
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        settings = await session.get(Settings, 1)
        if settings is None:
            raise RuntimeError("Settings not configured")
        return settings


def _job_backend(job: Job) -> dict:
    """Per-job backend config snapshot (SP-2). The worker reads transcription/
    translation/whisper config from here, never from global Settings."""
    snap = getattr(job, "backend_profile", None)
    if not snap:
        raise RuntimeError(
            "Job has no backend profile snapshot — resubmit from the submit sheet."
        )
    return snap


async def _fetch_job(job_id: str) -> Job | None:
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        return await session.get(Job, job_id)


async def _update_job(job_id: str, **fields) -> Job:
    from app.core.database import AsyncSessionLocal
    now = _utcnow()
    async with AsyncSessionLocal() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise RuntimeError(f"Job {job_id} not found")
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = now
        await session.commit()
        return job


def _set_job_failed_sync(job_id: str, message: str) -> None:
    """Fresh asyncio.run (NullPool-safe) to mark a job failed from the
    sync Celery context after retries are exhausted."""
    async def _do():
        await _update_job(job_id, status=JobStatus.failed, error_message=message)
    asyncio.run(_do())


async def _publish_event(redis_client: aioredis.Redis, job: Job) -> None:
    await redis_client.publish(_REDIS_CHANNEL, json.dumps(build_job_event_payload(job)))


async def _extract_audio(
    job: Job, job_id: str, audio_path: str, log_path: str, redis_client: aioredis.Redis
) -> None:
    import ffmpeg
    from app.core.security import validate_nas_path, ApiError

    settings = await _fetch_settings()

    try:
        validated_path = validate_nas_path(job.file_path, settings.nas_mount_path)
    except ApiError as e:
        raise RuntimeError(e.detail)

    job = await _update_job(job_id, phase=JobPhase.extracting, progress=5)
    _write_log(log_path, "INFO", job_id, f"Audio extraction started: {job.file_path}")
    await _publish_event(redis_client, job)

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: (
                ffmpeg
                .input(str(validated_path))
                .output(audio_path, acodec="pcm_s16le", ac=1, ar="16000")
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            ),
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg failed: {stderr}")

    job = await _update_job(job_id, progress=15)
    _write_log(log_path, "INFO", job_id, "Audio extraction completed")
    await _publish_event(redis_client, job)




def _compress_audio_for_remote(wav_path: str) -> str:
    """Transcode the extracted WAV to a small 16 kHz mono 32 kbps MP3 for
    hosted /v1/audio/transcriptions upload. Whisper resamples to 16 kHz
    mono internally, so speech-bitrate lossy compression has negligible
    WER impact; a 3.5 h film drops from ~400 MB WAV to ~40 MB, under
    hosted upload caps. Returns the new mp3 path (sibling of the WAV)."""
    import ffmpeg

    mp3_path = wav_path.rsplit(".", 1)[0] + ".remote.mp3"
    try:
        (
            ffmpeg
            .input(wav_path)
            .output(mp3_path, acodec="libmp3lame", ac=1, ar="16000", audio_bitrate="32k")
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
    except Exception:
        # Don't leave a partial .remote.mp3 in /tmp if ffmpeg dies mid-write
        # (the caller's finally only covers the post-return paths).
        try:
            os.remove(mp3_path)
        except OSError:
            pass
        raise
    return mp3_path


# Conservative single cap tuned for Groq's 100 MB limit. OpenAI's 25 MB
# limit is NOT enforced here by design (see spec §4.1) — an OpenAI
# long-film upload fails upstream with 413, surfaced by the error wrap.
_REMOTE_TRANSCRIPTION_MAX_BYTES = 95 * 1024 * 1024


def _guard_remote_audio_size(path: str) -> None:
    size = os.path.getsize(path)
    if size > _REMOTE_TRANSCRIPTION_MAX_BYTES:
        mb = size // (1024 * 1024)
        raise RuntimeError(
            f"Audio too large for hosted transcription ({mb} MB after "
            f"compression; cap {_REMOTE_TRANSCRIPTION_MAX_BYTES // (1024*1024)} MB) "
            f"— use a higher-limit transcription provider"
        )


def _wait_remote_ready(url: str, timeout: float = 90.0, interval: float = 10.0) -> None:
    """Best-effort warm-up: poll ``GET {url}/health`` until JSON
    ``model_loaded`` is truthy, up to ``timeout`` s. The self-hosted
    Whisper server idle-unloads (idle_timeout_s) and the first request
    after that cold-starts/500s — gating on /health removes that
    trigger. If /health 404s or isn't JSON, return immediately (don't
    assume every endpoint has it); never raises."""
    deadline = time.monotonic() + timeout
    health = f"{url.rstrip('/')}/health"
    while True:
        try:
            with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as c:
                r = c.get(health)
            if r.status_code == 404:
                return  # endpoint has no /health — proceed ungated
            if r.status_code < 400:
                body = r.json()
                if not isinstance(body, dict) or body.get("model_loaded", True):
                    return  # ready (or shape unknown → don't block)
        except Exception:
            pass  # unreachable/non-JSON → don't block on the warm-up itself
        if time.monotonic() >= deadline:
            return
        time.sleep(interval)


def _raise_transcription_http_error(e: "httpx.HTTPStatusError") -> None:
    """Transient httpx 5xx/429/408 → re-raise unchanged (``retry_call``
    owns backoff). Terminal 4xx → the surfaced ``RuntimeError`` (fail-fast;
    message byte-identical to the pre-resilience behaviour). Never returns."""
    from app.worker.errors import _TRANSIENT_STATUS

    if e.response.status_code in _TRANSIENT_STATUS:
        raise e
    msg = ""
    try:
        j = e.response.json()
        msg = (j.get("error", {}) or {}).get("message") or j.get("message") or ""
    except Exception:
        msg = (e.response.text or "")[:300]
    raise RuntimeError(
        f"Remote transcription failed: "
        f"{e.response.status_code} {e.response.reason_phrase} {msg}".strip()
    ) from e


def _run_transcription_remote_blocking(
    audio_path: str, url: str, model: str, api_key: str | None
) -> dict:
    """POST the extracted audio to an OpenAI-compatible /v1/audio/transcriptions
    endpoint (faster-whisper-server, speaches, etc.) and return ``{language,
    segments}`` shaped exactly like the local WhisperX path so downstream
    code is uniform.

    Uses a single long-poll request — the remote server is expected to hold
    the connection open while it runs inference (large-v3 on a 3hr file can
    be 20-40 min). The 1 hour ceiling is a safety net, not an expectation.
    """
    from app.worker.errors import retry_call

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    mp3_path = _compress_audio_for_remote(audio_path)
    try:
        _guard_remote_audio_size(mp3_path)
        endpoint = f"{url.rstrip('/')}/v1/audio/transcriptions"
        _wait_remote_ready(url)

        def _do_post() -> dict:
            with open(mp3_path, "rb") as f:
                files = {"file": (os.path.basename(mp3_path), f, "audio/mpeg")}
                data = {"model": model, "response_format": "verbose_json"}
                with httpx.Client(timeout=httpx.Timeout(3600.0, connect=30.0)) as client:
                    resp = client.post(endpoint, headers=headers, files=files, data=data)
                    try:
                        resp.raise_for_status()
                    except httpx.HTTPStatusError as e:
                        _raise_transcription_http_error(e)
                    return resp.json()

        body = retry_call(_do_post, step="remote-transcription", backoffs=[30.0, 120.0, 300.0])
    finally:
        try:
            os.remove(mp3_path)
        except OSError:
            pass

    language = body.get("language")
    segments_raw = body.get("segments") or []
    segments = [
        {"start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or "").strip()}
        for s in segments_raw
        if s.get("start") is not None and s.get("end") is not None
    ]
    return {"language": language, "segments": segments}


async def _transcribe(
    job: Job, job_id: str, audio_path: str, log_path: str, redis_client: aioredis.Redis
) -> list:
    """Transcription via an OpenAI-compatible /v1/audio/transcriptions endpoint.

    Local WhisperX was removed in May 2026 — the app's role is to orchestrate
    external AI backends, not to ship the ~20 GB CUDA/torch/whisperx stack.
    Self-host a Whisper server (faster-whisper-server, speaches, etc.) and
    point ``transcription_api_url`` at it.
    """
    b = _job_backend(job)
    url = b.get("transcription_api_url") or ""
    if not url:
        raise RuntimeError(
            "Transcription requires transcription_api_url to be configured in "
            "Settings → AI Backends → Transcription."
        )
    model = b.get("transcription_model") or "large-v3"

    job = await _update_job(job_id, phase=JobPhase.transcribing, progress=20)
    await _publish_event(redis_client, job)
    _write_log(
        log_path, "INFO", job_id,
        f"Transcription started (remote: {url}, model: {model})",
    )

    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        _run_transcription_remote_blocking,
        audio_path,
        url,
        model,
        b.get("transcription_api_key"),
    )
    language = result.get("language")
    segments = result.get("segments")
    if not language or segments is None:
        raise RuntimeError(
            f"Remote transcription returned unexpected shape: keys={list(result.keys())}"
        )
    job = await _update_job(job_id, source_language=language, progress=60)
    _write_log(
        log_path, "INFO", job_id,
        f"Transcription complete — language: {language}, segments: {len(segments)}",
    )
    await _publish_event(redis_client, job)
    # No alignment step — remote endpoint returns segment-level timestamps
    # which is what the SRT writer downstream consumes.
    return segments




def _resolve_litellm_target(
    provider: str, model: str, api_url: str | None, api_key: str | None
) -> tuple[str | None, str | None, str]:
    if provider == "ollama":
        return (api_url, api_key, f"ollama/{model}")
    if provider == "openai":
        return (None, api_key, model)
    if provider == "google":
        return (None, api_key, f"gemini/{model}")
    if provider == "openrouter":
        # OpenRouter is a fan-out gateway that proxies to many model
        # providers (Anthropic, OpenAI, Google, Mistral, Llama-family,
        # ...) behind a single OpenAI-compatible chat-completions API.
        # We hand-prefix `openrouter/` so the endpoint resolver below
        # routes to the OpenRouter URL instead of OpenAI's; the actual
        # model id (e.g. ``anthropic/claude-3.5-sonnet``) flows through
        # untouched inside the request body.
        return (None, api_key, f"openrouter/{model}")
    if provider == "custom":
        if not api_url:
            raise RuntimeError(
                "custom translation provider requires translation_api_url to be configured"
            )
        return (api_url, api_key, f"openai/{model}")
    raise RuntimeError(f"Unknown translation provider: {provider}")


def _resolve_translation_endpoint(mapped_model: str, base_url: str | None) -> tuple[str, str]:
    """Map a litellm-style ``mapped_model`` (``ollama/X``, ``gemini/X``,
    ``openai/X``, or bare model id) to (actual_model_name, endpoint_url).

    The prefixes are kept for backwards compatibility with the rest of the
    codebase that still thinks in litellm terms; the actual upstream wants
    the bare model name in the JSON body.
    """
    if "/" in mapped_model:
        prefix, actual_model = mapped_model.split("/", 1)
    else:
        prefix, actual_model = "openai", mapped_model

    if prefix == "openai" and not base_url:
        endpoint = "https://api.openai.com/v1/chat/completions"
    elif prefix == "gemini":
        endpoint = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    elif prefix == "openrouter":
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
    elif prefix in {"ollama", "openai"}:
        endpoint = f"{(base_url or '').rstrip('/')}/v1/chat/completions"
    else:
        # Unrecognized prefix — assume the caller pre-shaped base_url with
        # the right path and just POST there.
        endpoint = base_url or "https://api.openai.com/v1/chat/completions"
    return actual_model, endpoint


def _post_translation_with_retries(
    endpoint: str, headers: dict[str, str], body: dict
) -> tuple[str, dict]:
    """POST the translation request with up to 3 attempts. Returns
    ``(stripped_content, raw_response_dict)`` where the dict is the full
    parsed JSON (so upstream ``app.worker.usage.extract_usage`` can read
    both ``data["usage"]`` and the Ollama top-level eval-count fallback)."""
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                resp = client.post(endpoint, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
            content = data["choices"][0]["message"]["content"]
            if content is None:
                raise RuntimeError("Empty response from translation model")
            return content.strip(), (data if isinstance(data, dict) else {})
        except Exception as e:
            last_err = e
            if attempt >= 2:
                break
    from app.worker.errors import TransientPipelineError, is_transient
    if last_err is not None and is_transient(last_err):
        raise TransientPipelineError("translation", last_err) from last_err
    raise RuntimeError(f"Translation request failed after 3 attempts: {last_err}")


def _parse_glossary_response(raw: str) -> list[str]:
    """Best-effort JSON-array parser for glossary responses. Tolerates
    ``` ```json ``` fences, leading/trailing preamble around the array,
    non-string array entries, and duplicates. Returns ``[]`` on any
    failure so the caller can treat "no glossary" identically regardless
    of whether the model refused, returned prose, or returned malformed
    JSON."""
    import json

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1] if "```" in cleaned[3:] else cleaned[3:]
        if cleaned.startswith("json\n"):
            cleaned = cleaned[5:]
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        parsed = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    # Case-sensitive dedupe: "Spider" ≠ "spider" — both might legitimately
    # appear and the prompt explicitly preserves casing.
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


def _extract_glossary_blocking(
    joined_source: str,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
) -> tuple[list[str], dict]:
    """One upfront call: ask the LLM to extract every proper noun in the
    transcript that should NOT be translated. Returns
    ``(deduplicated_list_of_strings, raw_response_dict)`` so callers can
    extract usage metrics from the response. Errors (network, parse,
    refused) collapse to ``([], {})`` because the glossary is a quality
    boost, never a hard requirement."""
    from app.worker.translation_prompts import build_glossary_extraction_prompt

    actual_model, endpoint = _resolve_translation_endpoint(mapped_model, base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    system, user = build_glossary_extraction_prompt(joined_source)
    body = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"/no_think {user}"},
        ],
    }
    try:
        raw, data = _post_translation_with_retries(endpoint, headers, body)
    except Exception:
        return [], {}
    return _parse_glossary_response(raw), data


def _translate_segment_blocking(
    text: str,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    target_language: str,
    context_pairs: list[tuple[str, str]] | None = None,
    glossary: list[str] | None = None,
) -> tuple[str, dict]:
    """Translate one subtitle segment via a direct OpenAI-compatible chat
    completions POST. Returns ``(translated_text, raw_response_dict)``.

    The request uses a layered prompt:

    - **system** message — universal subtitle-translation rules (preserve
      proper nouns, match tone not words, don't add content, keep cues
      short) plus a per-language overlay loaded by ISO-639 code with
      typography + grammar conventions for that target.
    - **user** message — the actual line to translate, optionally
      preceded by the last N (source, translation) pairs from earlier in
      this film so the model keeps names and register consistent.

    All providers we support (Ollama, OpenAI, Google's OpenAI-compat
    layer, "Custom") speak the OpenAI chat-completions protocol; we
    bypass litellm entirely (it broke on the ``enterprise`` import in
    litellm 1.67.4) and POST via httpx directly.
    """
    from app.worker.translation_prompts import build_system_prompt, build_user_prompt

    actual_model, endpoint = _resolve_translation_endpoint(mapped_model, base_url)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    system_prompt = build_system_prompt(target_language, glossary=glossary)
    # ``/no_think`` suppresses chain-of-thought tokens on reasoning models
    # (qwen3.x, deepseek-r1, etc.). Non-reasoning models ignore it silently.
    user_prompt = f"/no_think {build_user_prompt(text, target_language, context_pairs)}"

    body = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    return _post_translation_with_retries(endpoint, headers, body)


def _format_translation_error(provider: str, model: str, exc: Exception) -> str:
    """Build the user-facing translation-failure message.

    Provider/HTTP exceptions can embed the API key (URL-encoded, prefixed,
    or whitespace-padded — substring redaction can't reliably catch it), so
    by default only the exception *class name* is surfaced. ``ImportError``
    (incl. ``ModuleNotFoundError``) is the one type whose message is
    generated by CPython's import machinery from the module name and is
    therefore provably credential-free — surface it, because "which
    module" is the only actionable detail and it was lost on job
    99bdab7a (2026-05-16)."""
    detail = type(exc).__name__
    if isinstance(exc, ImportError):
        detail = f"{detail}: {exc}"
    return f"Translation failed ({provider} / {model}): {detail}"


async def _translate_one_segment(
    loop,
    segment: dict,
    *,
    provider: str,
    model: str,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    target_language: str,
    context_pairs: list[tuple[str, str]] | None = None,
    glossary: list[str] | None = None,
    acc: UsageAccumulator,
) -> None:
    from app.worker.errors import TransientPipelineError

    original = (segment.get("text") or "").strip()
    if not original:
        return
    try:
        translated, data = await loop.run_in_executor(
            None,
            _translate_segment_blocking,
            original,
            mapped_model,
            base_url,
            api_key,
            target_language,
            context_pairs,
            glossary,
        )
    except TransientPipelineError:
        # A transient translation outage (provider 5xx/timeout, in-call
        # retries exhausted) MUST stay a TransientPipelineError so the
        # pipeline chokepoint marks the job queued and the Celery entry
        # self.retries it. The generic rewrapper below would downgrade it
        # to a terminal RuntimeError and dead-end the translation requeue.
        raise
    except Exception as e:
        # _format_translation_error owns the no-credential-leak rule; the
        # original exception stays chained via `from e` for the logger.
        raise RuntimeError(_format_translation_error(provider, model, e)) from e
    acc.add(extract_usage(data))
    segment["text"] = translated


async def _extract_and_log_glossary(
    loop,
    segments: list,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    log_path: str,
    job_id: str,
) -> tuple[list[str], dict]:
    """One upfront call before the per-segment loop: extract proper nouns
    from the entire transcript so they can be pinned as a glossary on
    every translation call. Catches long-range consistency issues the
    rolling context window can't — a name in cue 12 stays preserved in
    cue 847. Failures are non-fatal (empty glossary = pre-glossary
    behaviour). Logging here so ``_run_translation`` stays readable.

    Returns ``(glossary_list, raw_response_dict)`` so the caller can pass
    the dict to ``extract_usage`` for token/cost accounting."""
    joined_source = "\n".join(
        (s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip()
    )
    glossary, gloss_data = await loop.run_in_executor(
        None, _extract_glossary_blocking, joined_source, mapped_model, base_url, api_key,
    )
    if glossary:
        _write_log(
            log_path, "INFO", job_id,
            f"Glossary extracted: {len(glossary)} term(s) "
            f"({', '.join(glossary[:10])}{'…' if len(glossary) > 10 else ''})",
        )
    else:
        _write_log(log_path, "INFO", job_id, "Glossary extraction returned no terms")
    return glossary, gloss_data


async def _run_translation(
    job: Job, job_id: str, segments: list, log_path: str, redis_client: aioredis.Redis
) -> None:
    # Defense-in-depth: _async_pipeline already gates translation on
    # job.target_language (SP-2), so this is unreachable via the pipeline —
    # kept as a guard for any direct/future caller.
    if not job.target_language:
        raise RuntimeError("Translation requested but target_language is null")

    b = _job_backend(job)
    # enqueue_job always builds the snapshot with the full backend key set
    # (values may be None), so subscript is safe — a missing key here means
    # a corrupt snapshot, which should fail loudly rather than be papered over.
    provider = b["translation_provider"]
    model = b["translation_model"]
    if not model:
        raise RuntimeError("Translation requested but no model configured")

    base_url, api_key, mapped_model = _resolve_litellm_target(
        provider, model, b["translation_api_url"], b["translation_api_key"]
    )
    target_language = job.target_language

    job = await _update_job(job_id, phase=JobPhase.translating, progress=65)
    _write_log(
        log_path,
        "INFO",
        job_id,
        f"Translation started (provider: {provider}, model: {model}, target: {target_language})",
    )
    await _publish_event(redis_client, job)

    loop = asyncio.get_running_loop()
    acc = UsageAccumulator()
    glossary, gloss_data = await _extract_and_log_glossary(
        loop, segments, mapped_model, base_url, api_key, log_path, job_id
    )
    acc.add(extract_usage(gloss_data))

    # Translation is the longest phase by a wide margin (often 30-90 min for
    # a feature-length movie). Without per-segment progress, the Queue page
    # sits at 65% for the entire duration and users assume the job is stuck.
    # We map the [0..len(segments)) iteration onto the [65..80) progress
    # window and emit a job update whenever the integer percentage ticks
    # forward, plus a once-every-N-segments heartbeat so even slow-moving
    # bars confirm the worker is alive.
    total = max(1, len(segments))
    heartbeat_every = max(1, total // 20)  # ~20 SSE events per job, regardless of length
    last_emitted_progress = 65
    # Rolling window of (source, translation) pairs from the previous
    # CONTEXT_WINDOW_SIZE cues so the model keeps character names + register
    # consistent across the film. Per-language overlays + universal rules
    # live in app/worker/translation_prompts.py.
    from collections import deque

    from app.worker.translation_prompts import CONTEXT_WINDOW_SIZE

    recent_pairs: deque[tuple[str, str]] = deque(maxlen=CONTEXT_WINDOW_SIZE)
    for i, segment in enumerate(segments):
        original_text = (segment.get("text") or "").strip()
        await _translate_one_segment(
            loop,
            segment,
            provider=provider,
            model=model,
            mapped_model=mapped_model,
            base_url=base_url,
            api_key=api_key,
            target_language=target_language,
            context_pairs=list(recent_pairs),
            glossary=glossary,
            acc=acc,
        )
        # Record the translation we just produced for the next call's context.
        # Skip empty originals (already short-circuited in _translate_one_segment).
        translated_text = (segment.get("text") or "").strip()
        if original_text and translated_text:
            recent_pairs.append((original_text, translated_text))
        # Linear from 65 → 80 across the segment list. Stop at 79 so the
        # "Translation phase complete" emit below remains the clear 80-mark.
        new_progress = 65 + int(14 * (i + 1) / total)
        if new_progress > last_emitted_progress or ((i + 1) % heartbeat_every == 0):
            last_emitted_progress = new_progress
            job = await _update_job(job_id, progress=new_progress)
            await _publish_event(redis_client, job)

    # Ollama is local/free (reports no cost); every other provider's cost
    # is whatever its responses reported (None if any call omitted it).
    cost_usd = 0.0 if provider == "ollama" else acc.cost
    job = await _update_job(
        job_id,
        progress=80,
        prompt_tokens=acc.prompt_tokens,
        completion_tokens=acc.completion_tokens,
        total_tokens=acc.total_tokens,
        cost_usd=cost_usd,
        translation_provider=provider,
        translation_model=model,
    )
    _write_log(
        log_path, "INFO", job_id,
        f"Translation phase complete — tokens: {acc.total_tokens}, "
        f"cost: {'n/a' if cost_usd is None else f'${cost_usd:.4f}'}",
    )
    await _publish_event(redis_client, job)


async def _translate(
    job: Job, job_id: str, segments: list, log_path: str, redis_client: aioredis.Redis
) -> list:
    # _async_pipeline only calls this when job.target_language is set (the
    # SP-2 intent signal); the old `if job.translation_provider:` gate read
    # a legacy ORM column that SP-2 enqueue no longer populates (config now
    # lives in backend_profile) → translation silently skipped. Delegate;
    # _run_translation keeps its own defensive target_language guard.
    await _run_translation(job, job_id, segments, log_path, redis_client)
    return segments


def _format_srt_timestamp(seconds: float) -> str:
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        ms = 0
        s += 1
    if s >= 60:
        s = 0
        m += 1
    if m >= 60:
        m = 0
        h += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _segments_to_srt(segments: list) -> str:
    parts: list[str] = []
    for i, segment in enumerate(segments, start=1):
        start_val = segment.get("start")
        end_val = segment.get("end")
        if start_val is None or end_val is None:
            raise RuntimeError(f"Segment {i} missing required start/end timestamps")
        start = _format_srt_timestamp(float(start_val))
        end = _format_srt_timestamp(float(end_val))
        text = " ".join((segment.get("text") or "").splitlines()).strip()
        parts.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(parts)


def _output_srt_path(video_path: str, language: str) -> str:
    base, _ext = os.path.splitext(video_path)
    return f"{base}.{language}.srt"


async def _write_srt_for(
    job: Job, job_id: str, segments: list, lang: str, log_path: str, redis_client: aioredis.Redis
) -> str:
    from app.core.security import validate_nas_path, ApiError

    if not lang or "/" in lang or "\\" in lang or ".." in lang:
        raise RuntimeError(f"Invalid language code: {lang!r}")

    settings = await _fetch_settings()

    try:
        validated_video = validate_nas_path(job.file_path, settings.nas_mount_path)
    except ApiError as e:
        raise RuntimeError(e.detail) from e

    output_path = _output_srt_path(str(validated_video), lang)

    job = await _update_job(job_id, phase=JobPhase.writing, progress=90)
    _write_log(log_path, "INFO", job_id, f"Writing SRT to {output_path}")
    await _publish_event(redis_client, job)

    srt_content = _segments_to_srt(segments)

    def _write_atomically():
        tmp_path = f"{output_path}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            os.replace(tmp_path, output_path)
        except Exception:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            raise

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _write_atomically)

    _write_log(log_path, "INFO", job_id, "SRT write complete")
    return output_path


async def _trigger_jellyfin_refresh(
    job_id: str, log_path: str, redis_client: aioredis.Redis
) -> None:
    """call Jellyfin /Library/Refresh and stamp the job row.

    Reads credentials from the live settings row at call time (NOT from the
    job, which doesn't carry them) so the URL and API key never touch the
    per-job log file.
    """
    from app.services.jellyfin import trigger_library_scan_safe
    from app.worker.errors import is_transient

    settings = await _fetch_settings()
    if not settings.jellyfin_url or not settings.jellyfin_api_key:
        _write_log(log_path, "DEBUG", job_id, "Jellyfin not configured — skipping refresh")
        return

    backoffs = [5.0, 15.0, 30.0]
    refreshed = False
    for attempt in range(len(backoffs) + 1):
        try:
            refreshed = await trigger_library_scan_safe(settings)
            break
        except Exception as e:  # noqa: BLE001
            if is_transient(e) and attempt < len(backoffs):
                await asyncio.sleep(backoffs[attempt])
                continue
            _write_log(log_path, "WARN", job_id, f"Jellyfin refresh error (soft, not retried further): {e}")
            refreshed = False
            break
    if refreshed:
        now = _utcnow()
        job = await _update_job(job_id, jellyfin_refreshed_at=now)
        _write_log(log_path, "INFO", job_id, "Jellyfin library refresh triggered")
        await _publish_event(redis_client, job)
    else:
        _write_log(log_path, "WARN", job_id, "Jellyfin library refresh failed — see app logs")


async def _check_cancelled(job_id: str) -> bool:
    """Returns True if the job has been cancelled via the API since the last check.
    Worker uses this to abort gracefully at phase boundaries (cooperative cancellation)."""
    fresh = await _fetch_job(job_id)
    return fresh is None or fresh.status == JobStatus.cancelled


async def _check_cancel_after(job_id: str, log_path: str, phase: str) -> dict | None:
    """If the job has been cancelled, log + return the terminal result; else None."""
    if not await _check_cancelled(job_id):
        return None
    _write_log(log_path, "INFO", job_id, f"Job cancelled — aborting after {phase}")
    return {"status": JobStatus.cancelled, "srt_path": None}


async def _handle_pipeline_failure(
    job_id: str, exc: BaseException, log_path: str, redis_client
) -> None:
    """Persist the outcome of a failed pipeline step. Does NOT raise — the
    caller re-raises so the exception still propagates to the Celery entry.

    Transient / ``TransientPipelineError`` → mark the job ``queued``
    (auto-retry pending) so ``_run_generate`` can ``self.retry``. Terminal
    → mark ``failed`` with ``str(exc)`` (byte-identical to the
    pre-resilience behaviour).

    Latent-asymmetry note: every transient pipeline path today wraps as
    ``TransientPipelineError`` before reaching here (remote transcription
    via ``retry_call``; translation via ``_post_translation_with_retries``
    propagated by ``_translate_one_segment``), so the ``or is_transient``
    arm is currently defensive. A FUTURE step raising a *raw* httpx
    transient would be marked ``queued`` here but ``_run_generate`` only
    catches ``TransientPipelineError`` → orphaned ``queued``. Wrap any new
    such path in ``TransientPipelineError`` at the source (preferred), or
    widen ``_run_generate``'s except.
    """
    from app.worker.errors import TransientPipelineError, is_transient

    if isinstance(exc, TransientPipelineError) or is_transient(exc):
        step = exc.step if isinstance(exc, TransientPipelineError) else "pipeline"
        job = await _update_job(
            job_id,
            status=JobStatus.queued,
            error_message=f"Transient infra error ({step}); auto-retrying",
        )
        _write_log(log_path, "WARN", job_id, f"Transient failure ({step}) — will auto-retry: {exc}")
        await _publish_event(redis_client, job)
        return
    error_message = str(exc)
    job = await _update_job(job_id, status=JobStatus.failed, error_message=error_message)
    _write_log(log_path, "ERROR", job_id, f"Job failed: {error_message}")
    await _publish_event(redis_client, job)


async def _async_pipeline(job_id: str) -> dict:
    job = await _fetch_job(job_id)
    if job is None:
        return {"status": JobStatus.failed, "srt_path": None}

    # If the API cancelled the job before the worker picked it up, exit cleanly.
    if job.status == JobStatus.cancelled:
        return {"status": JobStatus.cancelled, "srt_path": None}

    log_path = f"{_LOG_DIR}/{job_id}.log"
    os.makedirs(_LOG_DIR, exist_ok=True)

    redis_client = aioredis.from_url(app_settings.redis_url)
    try:
        job = await _update_job(job_id, status=JobStatus.processing, log_path=log_path)
        _write_log(log_path, "INFO", job_id, "Job started — status=processing")
        await _publish_event(redis_client, job)

        audio_path = f"/tmp/{job_id}.wav"
        try:
            await _extract_audio(job, job_id, audio_path, log_path, redis_client)
            if (result := await _check_cancel_after(job_id, log_path, "extract")):
                return result
            src_segments = await _transcribe(job, job_id, audio_path, log_path, redis_client)
            if (result := await _check_cancel_after(job_id, log_path, "transcribe")):
                return result

            # Re-fetch to get the detected source_language set by _transcribe.
            job = await _fetch_job(job_id)
            src_lang = job.source_language

            source_srt = await _write_srt_for(job, job_id, src_segments, src_lang, log_path, redis_client)

            if job.target_language:
                translated_segments = await _translate(job, job_id, src_segments, log_path, redis_client)
                if (result := await _check_cancel_after(job_id, log_path, "translate")):
                    return result
                target_srt = await _write_srt_for(job, job_id, translated_segments, job.target_language, log_path, redis_client)
                srt_path = target_srt
            else:
                srt_path = source_srt

            now = _utcnow()
            job = await _update_job(
                job_id, status=JobStatus.completed, phase=JobPhase.done, progress=100, completed_at=now
            )
            _write_log(log_path, "INFO", job_id, f"Job completed successfully — {srt_path}")
            await _publish_event(redis_client, job)

            # fire-and-forget Jellyfin library refresh. Never
            # raises; failures stay out of the worker's success path.
            await _trigger_jellyfin_refresh(job_id, log_path, redis_client)
            return {"status": JobStatus.completed, "srt_path": srt_path}

        except Exception as exc:
            await _handle_pipeline_failure(job_id, exc, log_path, redis_client)
            raise
        finally:
            try:
                os.remove(audio_path)
            except OSError:
                pass
    finally:
        await redis_client.aclose()


_JOB_RETRY_BACKOFF = [60, 300, 900]   # 1m, 5m, 15m
_JOB_MAX_RETRIES = 2


def _run_generate(self, job_id: str) -> dict:
    from celery.exceptions import MaxRetriesExceededError
    from app.worker.errors import TransientPipelineError
    try:
        return asyncio.run(_async_pipeline(job_id))
    except TransientPipelineError as exc:
        n = self.request.retries  # 0 on first transient failure
        countdown = _JOB_RETRY_BACKOFF[min(n, len(_JOB_RETRY_BACKOFF) - 1)]
        try:
            raise self.retry(exc=exc, countdown=countdown, max_retries=_JOB_MAX_RETRIES)
        except MaxRetriesExceededError:
            _set_job_failed_sync(job_id, f"Failed after {_JOB_MAX_RETRIES} auto-retries: {exc.cause}")
            return {"status": JobStatus.failed, "srt_path": None}
    # Non-transient: the chokepoint already set status=failed; just let it surface.


@celery_app.task(name="generate_subtitles", bind=True, acks_late=True, reject_on_worker_lost=True)
def generate_subtitles(self, job_id: str) -> dict:
    return _run_generate(self, job_id)


