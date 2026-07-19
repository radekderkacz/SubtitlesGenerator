import asyncio
import json
import math
import os
import re
import time
from datetime import datetime, timezone

import httpx

import redis.asyncio as aioredis

from app.core.config import app_settings
from app.models.orm import Job, Settings, _utcnow
from app.models.schemas import JobStatus, JobPhase
from app.worker.asr_filters import filter_segments, normalize_lang_code
from app.worker.audio import extraction_filters, pick_audio_stream
from app.worker.langid import batch_language_suspect, language_check
from app.worker.shot_snap import detect_shot_changes, shot_snap_enabled, snap_cues_to_shots
from app.worker.vad import detect_speech_regions, save_regions, vad_disabled
from app.worker.celery_app import celery_app
from app.worker.cue_timing import (
    extract_words,
    format_cues,
    format_cues_from_segments,
    reflow_translated,
)
from app.worker.usage import UsageAccumulator, extract_usage

from app.services.job_events import REDIS_CHANNEL as _REDIS_CHANNEL, build_job_event_payload
from app.worker.subtitle_verify import verify as _verify_subtitles

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


class _JobCancelled(Exception):
    """Raised inside long phases when the job row flips to cancelled, so the
    pipeline can stop paying for work nobody wants (2026-07 audit)."""


async def _complete_job_if_processing(job_id: str, **fields) -> Job | None:
    """Compare-and-set terminal write: apply ``fields`` only while the job is
    still ``processing``. Returns the refreshed Job, or None when the update
    lost the race (e.g. a cancel landed between the last phase and here)."""
    from sqlalchemy import update as sa_update

    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            sa_update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.processing)
            .values(updated_at=_utcnow(), **fields)
        )
        await session.commit()
        if result.rowcount == 0:
            return None
        return await session.get(Job, job_id)


def _checkpoint_path(job_id: str) -> str:
    return f"{_LOG_DIR}/{job_id}.transcription.json"


def _translation_progress_path(job_id: str) -> str:
    return f"{_LOG_DIR}/{job_id}.translation.json"


def _load_translation_progress(job_id: str) -> dict[str, str]:
    """Per-cue translated texts from a previous attempt, keyed by segment
    index (as str). Empty dict when absent/unreadable."""
    try:
        with open(_translation_progress_path(job_id), encoding="utf-8") as f:
            data = json.load(f)
        texts = data.get("texts")
        return texts if isinstance(texts, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_translation_progress(job_id: str, texts: dict[str, str]) -> None:
    try:
        with open(_translation_progress_path(job_id), "w", encoding="utf-8") as f:
            json.dump({"texts": texts}, f)
    except OSError:
        pass


def _restore_saved_batch(saved: dict[str, str], idxs: range, chunk: list[dict]) -> bool:
    """When every cue of this batch was translated in a previous attempt,
    restore the texts and skip the LLM. Returns True when restored."""
    if not saved or not all(str(i) in saved for i in idxs):
        return False
    for i, seg in zip(idxs, chunk):
        seg["text"] = saved[str(i)]
    return True


def _save_transcription_checkpoint(job_id: str, result: dict) -> None:
    """Persist the (filtered) transcription so a job-level retry resumes at
    translation instead of re-running 20-40 min of GPU inference (2026-07
    audit HIGH-1). Best-effort: a write failure just means no resume."""
    try:
        with open(_checkpoint_path(job_id), "w", encoding="utf-8") as f:
            json.dump(result, f)
    except OSError:
        pass


def _load_transcription_checkpoint(job_id: str) -> dict | None:
    try:
        with open(_checkpoint_path(job_id), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) and data.get("segments") else None


def _clear_job_artifacts(job_id: str) -> None:
    """Drop resume artifacts on terminal states (the .vad.json stays — the
    post-completion sync check reads it)."""
    for path in (_checkpoint_path(job_id), _translation_progress_path(job_id)):
        try:
            os.remove(path)
        except OSError:
            pass


class _job_heartbeat:
    """Async context manager bumping the job's updated_at periodically while a
    long blocking call runs, so orphan recovery can tell "alive but silent"
    (a 30-min transcription POST) from "worker died"."""

    def __init__(self, job_id: str, interval: float = 60.0) -> None:
        self._job_id = job_id
        self._interval = interval
        self._task: asyncio.Task | None = None

    async def _beat(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await _update_job(self._job_id)
            # heartbeat must never kill the job
            except Exception:  # noqa: BLE001
                pass

    async def __aenter__(self) -> "_job_heartbeat":
        self._task = asyncio.create_task(self._beat())
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._task is not None:
            self._task.cancel()
            # awaiting a task WE just cancelled; suppress() keeps the intent
            # explicit without an except block that swallows a foreign cancel
            import contextlib
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


def _set_job_failed_sync(job_id: str, message: str) -> None:
    """Fresh asyncio.run (NullPool-safe) to mark a job failed from the
    sync Celery context after retries are exhausted."""
    async def _do():
        await _update_job(job_id, status=JobStatus.failed, error_message=message)
    asyncio.run(_do())


async def _publish_event(redis_client: aioredis.Redis, job: Job) -> None:
    await redis_client.publish(_REDIS_CHANNEL, json.dumps(build_job_event_payload(job)))


async def _select_dialogue_stream(
    loop, ffmpeg, path: str, job: Job, job_id: str, log_path: str
) -> tuple[dict | None, int | None]:
    """Pick the dialogue track explicitly — ffmpeg's default selects the
    most-channels stream, which on a typical MKV is a 5.1 commentary or a
    foreign dub (2026-07 audit). Probe failures fall back to the default."""
    try:
        probe_data = await loop.run_in_executor(None, ffmpeg.probe, path)
    # best-effort; default selection remains
    except Exception:  # noqa: BLE001
        _write_log(log_path, "WARNING", job_id,
                   "ffprobe failed — using ffmpeg default stream selection")
        return None, None
    if not isinstance(probe_data, dict):
        return None, None
    raw_hint = (job.source_language or "").strip().lower()
    hint = None if raw_hint in ("", "auto") else raw_hint
    stream, rel = pick_audio_stream(probe_data, hint)
    if stream is not None:
        lang = ((stream.get("tags") or {}).get("language")) or "und"
        _write_log(log_path, "INFO", job_id,
                   f"Selected audio stream a:{rel} "
                   f"(lang={lang}, {stream.get('channels')}ch)")
    return stream, rel


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
    stream, rel = await _select_dialogue_stream(
        loop, ffmpeg, str(validated_path), job, job_id, log_path)

    def _run_extraction():
        inp = ffmpeg.input(str(validated_path))
        src = inp[f"a:{rel}"] if rel is not None else inp
        kwargs = {"acodec": "pcm_s16le", "ac": 1, "ar": "16000"}
        af = extraction_filters(stream)
        if af:
            kwargs["af"] = af
        (ffmpeg.output(src, audio_path, **kwargs)
         .overwrite_output()
         .run(capture_stdout=True, capture_stderr=True))

    try:
        await loop.run_in_executor(None, _run_extraction)
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
    audio_path: str, url: str, model: str, api_key: str | None,
    *, language_hint: str | None = None,
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
                # Request word-level timestamps. httpx encodes the dict-with-list
                # value as repeated multipart fields; the list-of-tuples form
                # breaks its multipart encoding. The live segment-only server
                # ignores this field harmlessly — a word-capable backend honors
                # it and extract_words(...) then activates the word path.
                data = {
                    "model": model,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": ["segment", "word"],
                }
                if language_hint:
                    # The user's source-language hint stops Whisper from
                    # misdetecting on music/foreign-quote openings.
                    data["language"] = language_hint
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

    return {
        "language": body.get("language"),
        "segments": _reduce_response_segments(body.get("segments") or []),
        "words": extract_words(body),
    }


def _reduce_response_segments(segments_raw: list) -> list[dict]:
    """Reduce provider segments to the pipeline shape, keeping the confidence
    fields that feed the hallucination filters downstream
    (asr_filters.filter_segments); absent on some backends."""
    segments: list[dict] = []
    for s in segments_raw:
        if s.get("start") is None or s.get("end") is None:
            continue
        seg = {"start": s.get("start"), "end": s.get("end"), "text": (s.get("text") or "").strip()}
        for key in ("no_speech_prob", "avg_logprob", "compression_ratio"):
            if s.get(key) is not None:
                seg[key] = s[key]
        segments.append(seg)
    return segments


def _postprocess_transcription(
    result: dict,
    user_hint: str | None,
    speech_regions: list[tuple[float, float]] | None = None,
) -> tuple[dict, list[dict], str]:
    """Filter hallucinations out of a transcription and resolve the stored
    language (user hint wins over detection; both normalized to ISO-639-1).
    Words inside dropped segment ranges are removed so the word timing path
    can't resurrect filtered text. Raises when no speech survives."""
    filtered = filter_segments(result.get("segments") or [],
                               speech_regions=speech_regions)
    if not filtered.segments:
        raise RuntimeError(
            "No speech detected in the audio — no subtitles were generated"
        )
    out = dict(result, segments=filtered.segments)
    dropped_ranges = [
        (d.get("start"), d.get("end")) for d in filtered.dropped
        if d.get("start") is not None and d.get("end") is not None
    ]
    words = out.get("words") or []
    if words and dropped_ranges:
        out["words"] = [
            w for w in words
            if not any(s <= w["start"] < e for s, e in dropped_ranges)
        ]
    language = user_hint or normalize_lang_code(out.get("language"))
    return out, filtered.dropped, language


async def _transcribe(
    job: Job, job_id: str, audio_path: str, log_path: str, redis_client: aioredis.Redis,
    speech_regions: list[tuple[float, float]] | None = None,
) -> dict:
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

    raw_hint = (job.source_language or "").strip().lower()
    user_hint = normalize_lang_code(raw_hint) if raw_hint not in ("", "auto") else None

    loop = asyncio.get_running_loop()
    async with _job_heartbeat(job_id):
        result = await loop.run_in_executor(
            None,
            lambda: _run_transcription_remote_blocking(
                audio_path, url, model, b.get("transcription_api_key"),
                language_hint=user_hint,
            ),
        )
    detected = result.get("language")
    if not detected or result.get("segments") is None:
        raise RuntimeError(
            f"Remote transcription returned unexpected shape: keys={list(result.keys())}"
        )
    result, dropped, language = _postprocess_transcription(
        result, user_hint, speech_regions=speech_regions)
    for d in dropped:
        _write_log(log_path, "INFO", job_id,
                   f"Filtered segment ({d['reason']}) at {d['start']}: {d['text'][:80]!r}")
    if user_hint and normalize_lang_code(detected) != user_hint:
        _write_log(log_path, "WARNING", job_id,
                   f"Detected language {detected!r} differs from configured "
                   f"{user_hint!r} — keeping the configured language")
    segments = result["segments"]
    words = result.get("words") or []
    result["language"] = language
    job = await _update_job(job_id, source_language=language, progress=60)
    _write_log(
        log_path, "INFO", job_id,
        f"Transcription complete — language: {language}, segments: {len(segments)}, "
        f"words: {len(words)}, filtered: {len(dropped)} "
        f"({'word-level' if words else 'segment-level heuristic'} timing)",
    )
    await _publish_event(redis_client, job)
    # Return the full result so the pipeline can re-segment into speech-aligned
    # cues via build_source_cues (word path when words exist, else heuristic).
    return result




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


_TRANSLATION_BACKOFFS = [5.0, 15.0]


def _strip_think(content: str) -> str:
    """Remove chain-of-thought from reasoning-model replies. The ``/no_think``
    prefix only works on the Qwen3 family; DeepSeek-R1 and friends emit
    ``<think>…</think>`` regardless, and numbered lines inside the reasoning
    would otherwise be parsed as translations."""
    if "</think>" in content:
        content = content.rsplit("</think>", 1)[1]
    elif "<think>" in content:
        # Unclosed think block (truncated reasoning) — nothing usable follows.
        content = content.split("<think>", 1)[0]
    return content.strip()


def _post_translation_with_retries(
    endpoint: str, headers: dict[str, str], body: dict
) -> tuple[str, dict]:
    """POST the translation request. Transient failures (5xx/429/timeouts)
    back off between attempts and surface as TransientPipelineError when
    exhausted; terminal ones (401/400/…) fail fast on the first try instead
    of being hammered. Returns ``(content_without_think_tags,
    raw_response_dict)`` — the dict is the full parsed JSON so
    ``app.worker.usage.extract_usage`` can read usage/cost fields."""
    from app.worker.errors import retry_call

    def _do() -> tuple[str, dict]:
        with httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
            resp = client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        content = _strip_think(content) if content is not None else ""
        if not content:
            raise RuntimeError("Empty response from translation model")
        return content, (data if isinstance(data, dict) else {})

    return retry_call(_do, step="translation", backoffs=_TRANSLATION_BACKOFFS)


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


def _translation_headers(api_key: str | None) -> dict[str, str]:
    """JSON headers for an OpenAI-compatible translation POST, with optional bearer auth."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


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
    headers = _translation_headers(api_key)

    system, user = build_glossary_extraction_prompt(joined_source)
    body = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"/no_think {user}"},
        ],
        "temperature": TRANSLATION_TEMPERATURE,
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
    source_language: str | None = None,
    prior_reply: str | None = None,
    bible: dict | None = None,
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

    headers = _translation_headers(api_key)

    system_prompt = build_system_prompt(target_language, glossary=glossary, bible=bible)
    # ``/no_think`` suppresses chain-of-thought tokens on reasoning models
    # (qwen3.x, deepseek-r1, etc.). Non-reasoning models ignore it silently;
    # _strip_think handles models that emit <think> blocks regardless.
    user_prompt = (
        f"/no_think "
        f"{build_user_prompt(text, target_language, context_pairs, source_language=source_language)}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if prior_reply is not None:
        messages.append({"role": "assistant", "content": prior_reply})
        messages.append({"role": "user", "content": (
            "That reply was not a valid translation (it was empty, a refusal, "
            "or commentary). Reply with ONLY the translated line."
        )})
    body = {
        "model": actual_model,
        "messages": messages,
        "temperature": TRANSLATION_TEMPERATURE,
        # A runaway reasoning model must not burn minutes on one cue.
        "max_tokens": max(128, min(1024, 2 * len(text))),
    }

    return _post_translation_with_retries(endpoint, headers, body)


TRANSLATE_BATCH_SIZE = 10
# Glossary extraction window: ~6k chars ≈ 2k tokens keeps each call inside
# stock Ollama context limits (the OpenAI-compat endpoint can't set num_ctx,
# so an oversized prompt silently truncates — names from the last two acts
# of a film never made the glossary). Long films are sampled evenly.
GLOSSARY_CHUNK_CHARS = 6000
GLOSSARY_MAX_CHUNKS = 8
# Low, fixed sampling temperature for translation — faithful MT wants
# near-deterministic output. Default (~0.8) caused run-to-run quality
# variance that the verification judge flagged as "wording reads poorly".
TRANSLATION_TEMPERATURE = 0.2


def _parse_numbered_line(line: str) -> tuple[int, str] | None:
    """Parse a 'N. text' / 'N) text' / 'N: text' line into (N, text), or None.
    Hand-rolled (no regex) to keep it linear — no backtracking surface."""
    s = line.strip()
    i = 0
    while i < len(s) and s[i].isdigit():
        i += 1
    if i == 0 or i >= len(s) or s[i] not in ".):":
        return None
    text = s[i + 1:].strip()
    if not text:
        return None
    return int(s[:i]), text


def _parse_batch_response(raw: str, n: int) -> list[str] | None:
    """Parse a numbered translation reply into a list aligned to the N inputs,
    or None if it doesn't contain exactly numbers 1..N with non-empty text."""
    found: dict[int, str] = {}
    for line in raw.splitlines():
        parsed = _parse_numbered_line(line)
        if parsed is None:
            continue
        idx, text = parsed
        if idx in found:
            # A duplicated number means the model renumbered or leaked
            # reasoning — trusting either occurrence risks mapping the wrong
            # text to a cue. Treat the whole reply as misaligned.
            return None
        found[idx] = text
    if len(found) != n or any(k not in found for k in range(1, n + 1)):
        return None
    return [found[k] for k in range(1, n + 1)]


def _translate_batch_blocking(
    texts: list[str],
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    target_language: str,
    context_pairs: list[tuple[str, str]] | None = None,
    glossary: list[str] | None = None,
    source_language: str | None = None,
    prior_reply: str | None = None,
    bible: dict | None = None,
    story_so_far: str | None = None,
) -> tuple[list[str] | None, str, dict]:
    """One POST translating a batch of cues. Returns (aligned list | None,
    raw_reply, raw_response_dict). None signals misalignment — including a
    reply truncated by max_tokens — so the caller can corrective-re-ask or
    fall back to per-cue. ``prior_reply`` turns the call into that corrective
    re-ask: the bad reply is quoted as assistant context with an explicit
    complaint."""
    from app.worker.translation_prompts import build_batch_system_prompt, build_batch_user_prompt

    actual_model, endpoint = _resolve_translation_endpoint(mapped_model, base_url)
    headers = _translation_headers(api_key)
    system_prompt = build_batch_system_prompt(target_language, glossary=glossary, bible=bible)
    user_prompt = (
        f"/no_think "
        f"{build_batch_user_prompt(texts, target_language, context_pairs, source_language=source_language, story_so_far=story_so_far)}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    if prior_reply is not None:
        messages.append({"role": "assistant", "content": prior_reply})
        messages.append({"role": "user", "content": (
            f"That reply did not contain exactly {len(texts)} numbered lines "
            f"(1..{len(texts)}, one per input cue). Re-emit ALL {len(texts)} "
            f"translations in that exact format and nothing else."
        )})
    body = {
        "model": actual_model,
        "messages": messages,
        "temperature": TRANSLATION_TEMPERATURE,
        # Sized to the batch so a runaway reasoning model can't stall the job.
        "max_tokens": max(256, min(4096, sum(len(t) for t in texts) + 64 * len(texts))),
    }
    raw, data = _post_translation_with_retries(endpoint, headers, body)
    finish = ((data.get("choices") or [{}])[0] or {}).get("finish_reason")
    if finish == "length":
        # Truncated list: the tail cues would be missing — never accept it.
        return None, raw, data
    return _parse_batch_response(raw, len(texts)), raw, data


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


from dataclasses import dataclass, field


@dataclass
class _TranslateTarget:
    """Everything a translation call needs to know about WHERE it is going
    and WHAT film context it carries — one object instead of nine params."""
    provider: str
    model: str
    mapped_model: str
    base_url: str | None
    api_key: str | None
    target_language: str
    source_language: str | None = None
    glossary: list[str] | None = None
    bible: dict | None = field(default=None, repr=False)


_REFUSAL_PREFIXES = (
    "i'm sorry", "i am sorry", "i cannot", "i can't", "i won't",
    "as an ai", "as a language model", "here is", "here's",
)


def _clean_single_translation(original: str, translated: str) -> str | None:
    """Validate a per-cue reply: strip wrapping quotes; reject empties,
    refusal/preamble phrases, and implausible length blowups (>4×). Returns
    the cleaned text or None when the reply must not be shipped."""
    t = translated.strip()
    for opener, closer in (('"', '"'), ("'", "'"), ("„", "”"), ("«", "»")):
        if len(t) > 1 and t.startswith(opener) and t.endswith(closer):
            t = t[1:-1].strip()
    if not t:
        return None
    low = t.lower()
    if any(low.startswith(p) for p in _REFUSAL_PREFIXES):
        return None
    if len(t) > 4 * max(len(original), 20):
        return None
    return t


async def _translate_one_segment(
    loop,
    segment: dict,
    tgt: _TranslateTarget,
    *,
    context_pairs: list[tuple[str, str]] | None = None,
    acc: UsageAccumulator,
) -> None:
    """Translate one cue with output validation: an invalid reply (refusal,
    preamble, blowup) gets ONE corrective re-ask; if that also fails, the
    source text is kept — an untranslated line beats shipped garbage, and
    verification's language checks surface it."""
    from app.worker.errors import TransientPipelineError

    original = (segment.get("text") or "").strip()
    if not original:
        return
    prior_reply: str | None = None
    for _ in range(2):
        try:
            translated, data = await loop.run_in_executor(
                None,
                lambda prior=prior_reply: _translate_segment_blocking(
                    original, tgt.mapped_model, tgt.base_url, tgt.api_key,
                    tgt.target_language, context_pairs, tgt.glossary,
                    source_language=tgt.source_language, prior_reply=prior,
                    bible=tgt.bible,
                ),
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
            raise RuntimeError(_format_translation_error(tgt.provider, tgt.model, e)) from e
        acc.add(extract_usage(data))
        cleaned = _clean_single_translation(original, translated)
        if cleaned is not None:
            segment["text"] = cleaned
            return
        prior_reply = translated
    # Both attempts invalid: keep the source text (never ship a refusal) and
    # flag the cue for the post-translation repair pass.
    segment["needs_repair"] = True


async def _translate_batch(
    loop,
    chunk: list[dict],
    tgt: _TranslateTarget,
    *,
    context_pairs: list[tuple[str, str]] | None = None,
    story_so_far: str | None = None,
    acc: UsageAccumulator,
) -> None:
    """Translate a chunk in one call. A misaligned reply gets ONE corrective
    re-ask (with the bad reply quoted) — most misalignments recover in that
    single cheap call — before falling back to the per-cue path for each
    non-empty cue. Empty cues are left untouched."""
    from app.worker.errors import TransientPipelineError

    nonempty = [s for s in chunk if (s.get("text") or "").strip()]
    if not nonempty:
        return
    texts = [(s.get("text") or "").strip() for s in nonempty]
    result: list[str] | None = None
    prior_reply: str | None = None
    for _ in range(2):
        try:
            result, raw, data = await loop.run_in_executor(
                None,
                lambda prior=prior_reply: _translate_batch_blocking(
                    texts, tgt.mapped_model, tgt.base_url, tgt.api_key,
                    tgt.target_language, context_pairs, tgt.glossary,
                    source_language=tgt.source_language, prior_reply=prior,
                    bible=tgt.bible, story_so_far=story_so_far,
                ),
            )
        except TransientPipelineError:
            raise
        except Exception as e:
            raise RuntimeError(_format_translation_error(tgt.provider, tgt.model, e)) from e
        acc.add(extract_usage(data))
        if _accept_batch_result(nonempty, result, tgt, first_attempt=prior_reply is None):
            return
        prior_reply = raw

    for seg in nonempty:
        await _translate_one_segment(loop, seg, tgt, context_pairs=context_pairs, acc=acc)


def _accept_batch_result(
    nonempty: list[dict], result: list[str] | None, tgt: _TranslateTarget,
    *, first_attempt: bool,
) -> bool:
    """Apply an aligned batch reply unless (on the first attempt) it reads as
    an untranslated source-language echo. Returns True when applied."""
    if result is None:
        return False
    if first_attempt and batch_language_suspect(
            result, tgt.target_language, tgt.source_language):
        return False
    for seg, translated in zip(nonempty, result):
        seg["text"] = translated
    return True


# Scene-aware batching (2026-07 audit WS8): a silence gap between cues almost
# always means a scene change, and translation context should not leak across
# it. Batches cap at SCENE_BATCH_MAX_CUES so max_tokens stays predictable and
# a single bad reply loses at most one scene's worth of work.
SCENE_GAP_SECONDS = 4.0
SCENE_BATCH_MAX_CUES = 15
SCENE_BATCH_MIN_CUES = 5
STORY_SUMMARY_EVERY_N_BATCHES = 5
STORY_SUMMARY_MAX_CHARS = 400


def batch_cues_by_scene(segments: list[dict]) -> list[list[dict]]:
    """Group consecutive cues into scene-shaped translation batches: a new
    batch starts at a silence gap (once the current batch has a useful
    minimum) or at the size cap."""
    batches: list[list[dict]] = []
    cur: list[dict] = []
    for seg in segments:
        if cur:
            gap = (seg.get("start") or 0.0) - (cur[-1].get("end") or 0.0)
            scene_break = gap > SCENE_GAP_SECONDS and len(cur) >= SCENE_BATCH_MIN_CUES
            if scene_break or len(cur) >= SCENE_BATCH_MAX_CUES:
                batches.append(cur)
                cur = []
        cur.append(seg)
    if cur:
        batches.append(cur)
    return batches


def _parse_bible_response(raw: str) -> dict:
    """Best-effort parser for the film-bible JSON object. Tolerates markdown
    fences and surrounding prose; any failure returns {} (bible is a quality
    boost, never a requirement)."""
    import json as _json

    cleaned = raw.replace("```json", "```").strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = max(parts, key=len)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        data = _json.loads(cleaned[start:end + 1])
    except _json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    _parse_bible_lists(data, out)
    terms = data.get("terms")
    if isinstance(terms, dict):
        out["terms"] = {str(k): str(v) for k, v in terms.items() if k and v}
    for key in ("setting", "register"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            out[key] = val.strip()
    return out


def _parse_bible_lists(data: dict, out: dict) -> None:
    names = data.get("names")
    if isinstance(names, list):
        out["names"] = [n.strip() for n in names if isinstance(n, str) and n.strip()]
    chars = data.get("characters")
    if isinstance(chars, list):
        out["characters"] = [
            {"name": c["name"].strip(), "gender": str(c.get("gender") or "unknown")}
            for c in chars
            if isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"].strip()
        ]


def _merge_bible_names(b: dict, merged: dict, seen_names: set[str], chars: dict[str, str]) -> None:
    for n in b.get("names") or []:
        if n not in seen_names:
            seen_names.add(n)
            merged["names"].append(n)
    for c in b.get("characters") or []:
        prev = chars.get(c["name"])
        if prev is None or (prev == "unknown" and c.get("gender") != "unknown"):
            chars[c["name"]] = c.get("gender") or "unknown"


def _merge_one_bible(b: dict, merged: dict, seen_names: set[str], chars: dict[str, str]) -> None:
    _merge_bible_names(b, merged, seen_names, chars)
    for src, tgt in (b.get("terms") or {}).items():
        merged["terms"].setdefault(src, tgt)
    for key in ("setting", "register"):
        if not merged[key] and b.get(key):
            merged[key] = b[key]


def _merge_bibles(bibles: list[dict]) -> dict:
    """Merge per-chunk bibles: ordered union for names/characters (first
    gender wins unless it was 'unknown'), first-wins for terms and prose."""
    merged: dict = {"names": [], "characters": [], "terms": {}, "setting": "", "register": ""}
    seen_names: set[str] = set()
    chars: dict[str, str] = {}
    for b in bibles:
        _merge_one_bible(b, merged, seen_names, chars)
    merged["characters"] = [{"name": n, "gender": g} for n, g in chars.items()]
    return merged


def _extract_bible_blocking(
    chunk: str,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    target_language: str,
) -> tuple[dict, dict]:
    """One film-bible extraction call over a transcript window. Errors
    collapse to ({}, {})."""
    from app.worker.translation_prompts import build_bible_extraction_prompt

    actual_model, endpoint = _resolve_translation_endpoint(mapped_model, base_url)
    headers = _translation_headers(api_key)
    system, user = build_bible_extraction_prompt(chunk, target_language)
    body = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"/no_think {user}"},
        ],
        "temperature": TRANSLATION_TEMPERATURE,
        "max_tokens": 1024,
    }
    try:
        raw, data = _post_translation_with_retries(endpoint, headers, body)
    # bible is best-effort
    except Exception:  # noqa: BLE001
        return {}, {}
    return _parse_bible_response(raw), data


def _update_story_summary_blocking(
    prev_summary: str,
    recent_lines: list[str],
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
) -> str:
    """Refresh the rolling two-sentence story summary. Failures keep the
    previous summary."""
    actual_model, endpoint = _resolve_translation_endpoint(mapped_model, base_url)
    headers = _translation_headers(api_key)
    user = (
        "Update this running story summary of a film using the newest "
        "dialogue. Reply with ONLY the updated summary, at most two "
        "sentences.\n\n"
        f"Current summary: {prev_summary or '(none yet)'}\n\n"
        "Newest dialogue:\n" + "\n".join(recent_lines)
    )
    body = {
        "model": actual_model,
        "messages": [{"role": "user", "content": f"/no_think {user}"}],
        "temperature": TRANSLATION_TEMPERATURE,
        "max_tokens": 200,
    }
    try:
        raw, _data = _post_translation_with_retries(endpoint, headers, body)
    # summary is best-effort
    except Exception:  # noqa: BLE001
        return prev_summary
    return raw.strip()[:STORY_SUMMARY_MAX_CHARS] or prev_summary


def _transcript_chunks(joined_source: str) -> list[str]:
    """Split a transcript into glossary-extraction windows, evenly sampling
    when the film is too long to send every window."""
    chunks = [
        joined_source[i:i + GLOSSARY_CHUNK_CHARS]
        for i in range(0, len(joined_source), GLOSSARY_CHUNK_CHARS)
    ] or [""]
    if len(chunks) > GLOSSARY_MAX_CHUNKS:
        step = len(chunks) / GLOSSARY_MAX_CHUNKS
        chunks = [chunks[int(i * step)] for i in range(GLOSSARY_MAX_CHUNKS)]
    return chunks


async def _extract_film_bible(
    loop,
    segments: list,
    mapped_model: str,
    base_url: str | None,
    api_key: str | None,
    log_path: str,
    job_id: str,
    target_language: str,
) -> tuple[dict, list[dict]]:
    """One upfront call before the per-segment loop: extract proper nouns
    from the entire transcript so they can be pinned as a glossary on
    every translation call. Catches long-range consistency issues the
    rolling context window can't — a name in cue 12 stays preserved in
    cue 847. Failures are non-fatal (empty glossary = pre-glossary
    behaviour). Logging here so ``_run_translation`` stays readable.

    The transcript is chunked (~GLOSSARY_CHUNK_CHARS per call, at most
    GLOSSARY_MAX_CHUNKS evenly-sampled windows) so local models with small
    context windows (stock Ollama num_ctx) see every act of the film instead
    of silently truncating to the first 15 minutes.

    Returns ``(glossary_list, [raw_response_dict, ...])`` so the caller can
    pass each dict to ``extract_usage`` for token/cost accounting."""
    joined_source = "\n".join(
        (s.get("text") or "").strip() for s in segments if (s.get("text") or "").strip()
    )
    bibles: list[dict] = []
    datas: list[dict] = []
    for chunk in _transcript_chunks(joined_source):
        bible_part, data = await loop.run_in_executor(
            None, _extract_bible_blocking, chunk, mapped_model, base_url, api_key,
            target_language,
        )
        if bible_part:
            bibles.append(bible_part)
        datas.append(data)
    bible = _merge_bibles(bibles)
    names = bible.get("names") or []
    if names or bible.get("characters"):
        _write_log(
            log_path, "INFO", job_id,
            f"Film bible extracted: {len(names)} name(s), "
            f"{len(bible.get('characters') or [])} character(s), "
            f"{len(bible.get('terms') or {})} pinned term(s)",
        )
    else:
        _write_log(log_path, "INFO", job_id, "Film bible extraction returned nothing")
    return bible, datas


class _TranslationContext:
    """Rolling cross-batch state: continuity pairs, recent source lines for
    the story summary, and the summary itself."""

    def __init__(self) -> None:
        from collections import deque as _deque

        from app.worker.translation_prompts import CONTEXT_WINDOW_SIZE as _N
        self.recent_pairs = _deque(maxlen=_N)
        self.recent_sources = _deque(maxlen=30)
        self.story_summary = ""

    def remember(self, originals: list[str], chunk: list[dict]) -> None:
        for orig, seg in zip(originals, chunk):
            translated = (seg.get("text") or "").strip()
            if orig and translated:
                self.recent_pairs.append((orig, translated))
        self.recent_sources.extend(o for o in originals if o)


async def _raise_if_cancelled(job_id: str, log_path: str, done: int, total: int) -> None:
    current = await _fetch_job(job_id)
    if current is not None and current.status == JobStatus.cancelled:
        _write_log(log_path, "INFO", job_id,
                   f"Cancelled mid-translation after {done}/{total} cues — stopping")
        raise _JobCancelled()


async def _tick_translation_progress(
    job_id: str, redis_client: aioredis.Redis, done: int, total: int, last: int
) -> int:
    """Emit a progress update when the integer percentage ticks forward.
    Linear from 65 → 80 across the segment list; stops at 79 so the
    "Translation phase complete" emit remains the clear 80-mark."""
    new_progress = 65 + int(14 * done / total)
    if new_progress <= last:
        return last
    job = await _update_job(job_id, progress=new_progress)
    await _publish_event(redis_client, job)
    return new_progress


REPAIR_MAX_CUES = 50


def _flag_untranslated_cues(segments: list[dict], target_language: str | None,
                            source_language: str | None) -> None:
    """Post-loop sweep: a long cue that still reads as the SOURCE language is
    an untranslated leftover — flag it for repair."""
    for seg in segments:
        if seg.get("needs_repair"):
            continue
        text = (seg.get("text") or "").strip()
        if len(text) < 40:
            continue
        if batch_language_suspect([text], target_language, source_language):
            seg["needs_repair"] = True


async def _repair_pass(
    loop,
    segments: list[dict],
    tgt: _TranslateTarget,
    *,
    acc: UsageAccumulator,
    log_path: str,
    job_id: str,
) -> int:
    """Second-pass repair of flagged cues (refusals kept as source,
    untranslated leftovers): one stern per-cue retry each, with neighbor
    context, bounded to REPAIR_MAX_CUES. Returns the number repaired."""
    flagged = [i for i, seg in enumerate(segments) if seg.get("needs_repair")]
    for i in flagged[REPAIR_MAX_CUES:]:
        segments[i].pop("needs_repair", None)
    if len(flagged) > REPAIR_MAX_CUES:
        _write_log(log_path, "WARNING", job_id,
                   f"repair pass capped: {len(flagged)} flagged, "
                   f"repairing first {REPAIR_MAX_CUES}")
        flagged = flagged[:REPAIR_MAX_CUES]
    repaired = 0
    for i in flagged:
        seg = segments[i]
        try:
            translated, data = await loop.run_in_executor(
                None,
                lambda text=seg["text"]: _translate_segment_blocking(
                    text, tgt.mapped_model, tgt.base_url, tgt.api_key,
                    tgt.target_language, context_pairs=None, glossary=tgt.glossary,
                    source_language=tgt.source_language, bible=tgt.bible,
                ),
            )
        # repair is best-effort
        except Exception:  # noqa: BLE001
            continue
        acc.add(extract_usage(data))
        cleaned = _clean_single_translation(seg.get("text") or "", translated)
        if cleaned is not None:
            seg["text"] = cleaned
            seg.pop("needs_repair", None)
            repaired += 1
    return repaired


async def _run_batch_loop(
    loop, tgt: _TranslateTarget, segments: list, job_id: str, log_path: str,
    redis_client: aioredis.Redis, acc: UsageAccumulator,
) -> None:
    """Scene-batched translation with per-batch progress, cross-batch
    continuity, per-batch resume checkpoints, story-summary refreshes, and a
    per-batch cancellation check.

    Translation is the longest phase by a wide margin (often 30-90 min for a
    feature-length movie); progress maps the iteration onto the [65..80)
    window so the Queue page never looks stuck."""
    total = max(1, len(segments))
    last_emitted_progress = 65
    ctx = _TranslationContext()
    saved_texts = _load_translation_progress(job_id)
    if saved_texts:
        _write_log(log_path, "INFO", job_id,
                   f"Resuming translation — {len(saved_texts)} cue(s) already "
                   f"translated in a previous attempt")
    done = 0
    offset = 0
    for batch_no, chunk in enumerate(batch_cues_by_scene(segments)):
        idxs = range(offset, offset + len(chunk))
        offset += len(chunk)
        originals = [(s.get("text") or "").strip() for s in chunk]
        if _restore_saved_batch(saved_texts, idxs, chunk):
            ctx.remember(originals, chunk)
            done += len(chunk)
            continue
        await _raise_if_cancelled(job_id, log_path, done, total)
        await _translate_batch(
            loop, chunk, tgt,
            context_pairs=list(ctx.recent_pairs),
            story_so_far=ctx.story_summary or None,
            acc=acc,
        )
        for i, seg in zip(idxs, chunk):
            saved_texts[str(i)] = seg.get("text") or ""
        _save_translation_progress(job_id, saved_texts)
        ctx.remember(originals, chunk)
        if (batch_no + 1) % STORY_SUMMARY_EVERY_N_BATCHES == 0:
            ctx.story_summary = await loop.run_in_executor(
                None, _update_story_summary_blocking, ctx.story_summary,
                list(ctx.recent_sources), tgt.mapped_model, tgt.base_url, tgt.api_key,
            )
        done += len(chunk)
        last_emitted_progress = await _tick_translation_progress(
            job_id, redis_client, done, total, last_emitted_progress
        )


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
    bible, gloss_datas = await _extract_film_bible(
        loop, segments, mapped_model, base_url, api_key, log_path, job_id,
        target_language,
    )
    for gloss_data in gloss_datas:
        acc.add(extract_usage(gloss_data))
    tgt = _TranslateTarget(
        provider=provider, model=model, mapped_model=mapped_model,
        base_url=base_url, api_key=api_key, target_language=target_language,
        source_language=job.source_language,
        glossary=bible.get("names") or [], bible=bible,
    )

    await _run_batch_loop(loop, tgt, segments, job_id, log_path, redis_client, acc)

    _flag_untranslated_cues(segments, target_language, job.source_language)
    repaired = await _repair_pass(loop, segments, tgt,
                                  acc=acc, log_path=log_path, job_id=job_id)
    if repaired:
        _write_log(log_path, "INFO", job_id,
                   f"Repair pass fixed {repaired} suspect cue(s)")

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


def build_source_cues(transcription) -> list[dict]:
    """Re-segment a transcription into speech-aligned, reading-speed-bounded cues.

    Word path: when the backend returns word-level timestamps, regroup words
    into sentence cues. Heuristic path (the live segment-only server): split
    each segment's text into sentences and distribute its time span across them.
    Both apply the same timing + line-wrapping rules. Accepts a bare segment
    list as a no-words transcription for defensive/legacy callers.
    """
    if isinstance(transcription, dict):
        words = transcription.get("words") or []
        segments = transcription.get("segments") or []
    else:
        words, segments = [], (transcription or [])
    if words:
        return format_cues(words)
    return format_cues_from_segments(segments)


def _segments_to_srt(segments: list) -> str:
    parts: list[str] = []
    for i, segment in enumerate(segments, start=1):
        start_val = segment.get("start")
        end_val = segment.get("end")
        if start_val is None or end_val is None:
            raise RuntimeError(f"Segment {i} missing required start/end timestamps")
        start = _format_srt_timestamp(float(start_val))
        end = _format_srt_timestamp(float(end_val))
        # Preserve intentional line wrapping (cues are wrapped to <=2 lines by
        # wrap_lines — a valid multi-line SRT cue). Strip each line and drop
        # blank lines so a stray double newline can't break cue boundaries.
        lines = [ln.strip() for ln in (segment.get("text") or "").splitlines() if ln.strip()]
        text = "\n".join(lines)
        parts.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(parts)


def _output_srt_path(video_path: str, language: str) -> str:
    base, _ext = os.path.splitext(video_path)
    return f"{base}.{language}.srt"


async def _write_srt_for(
    job: Job, job_id: str, segments: list, lang: str, log_path: str, redis_client: aioredis.Redis
) -> str:
    from app.core.security import validate_nas_path, ApiError

    # Normalize provider full names / ISO-639-2 codes so players map the
    # suffix ("Movie.en.srt", never "Movie.english.srt").
    lang = normalize_lang_code(lang)
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
    _clear_job_artifacts(job_id)  # terminal: resume artifacts are dead weight
    job = await _update_job(job_id, status=JobStatus.failed, error_message=error_message)
    _write_log(log_path, "ERROR", job_id, f"Job failed: {error_message}")
    await _publish_event(redis_client, job)


async def _maybe_snap_to_shots(
    job: Job, job_id: str, cues: list[dict], log_path: str
) -> list[dict]:
    """Opt-in shot-change snapping (SUBGEN_SHOT_SNAP=1): one scene-detection
    pass, boundaries near cuts move onto them, output invariants re-applied.
    Translated cues inherit the snapped timing (they copy it 1:1)."""
    if not shot_snap_enabled():
        return cues
    from app.worker.cue_timing import apply_invariants

    loop = asyncio.get_running_loop()
    cuts = await loop.run_in_executor(None, detect_shot_changes, job.file_path)
    if not cuts:
        _write_log(log_path, "INFO", job_id, "Shot snap: no cuts detected — skipping")
        return cues
    _write_log(log_path, "INFO", job_id,
               f"Shot snap: aligning cue boundaries to {len(cuts)} cut(s)")
    return apply_invariants(snap_cues_to_shots(cues, cuts))


async def _run_vad(job_id: str, audio_path: str, log_path: str):
    """Client-side VAD: speech regions reject hallucinated segments over
    silence/music and feed the sync self-check. Best-effort — None means
    "no information" and disables the rejection."""
    if vad_disabled():
        return None
    loop = asyncio.get_running_loop()
    speech_regions = await loop.run_in_executor(None, detect_speech_regions, audio_path)
    if speech_regions is not None:
        total = sum(e - s for s, e in speech_regions)
        _write_log(log_path, "INFO", job_id,
                   f"VAD: {len(speech_regions)} speech region(s), "
                   f"{total/60:.1f} min of speech")
        save_regions(f"{_LOG_DIR}/{job_id}.vad.json", speech_regions)
    return speech_regions


async def _translate_phase(
    job: Job, job_id: str, src_cues: list[dict], log_path: str,
    redis_client: aioredis.Redis,
):
    """Translate per cue on unwrapped copies (1:1, source-derived timing
    preserved) so no source line breaks reach the model; reflow_translated
    re-times + re-wraps. Returns the target SRT path, or the cancel result
    dict when the job was cancelled mid-phase."""
    translate_cues = [
        {"start": c["start"], "end": c["end"], "text": " ".join(c["text"].splitlines())}
        for c in src_cues
    ]
    translated_cues = await _translate(job, job_id, translate_cues, log_path, redis_client)
    if (result := await _check_cancel_after(job_id, log_path, "translate")):
        return result
    translated_cues = reflow_translated(translated_cues)
    return await _write_srt_for(
        job, job_id, translated_cues, job.target_language, log_path, redis_client)


# ---------------------------------------------------------------------------
# Existing-subtitle gate: use a verified shipped subtitle track instead of ASR
# ---------------------------------------------------------------------------

_EXISTING_SUBS_MAX_CANDIDATES = 4


def _existing_subs_enabled(job: Job) -> bool:
    if os.environ.get("SUBGEN_DISABLE_EXISTING_SUBS", "").lower() in ("1", "true", "yes"):
        return False
    return bool(getattr(job, "use_existing_subs", True))


def _candidate_cues(job: Job, job_id: str, cand) -> tuple[list[dict], str | None] | None:
    """Read (sidecar) or extract (embedded) a candidate, parse, strip SDH.
    Returns (cues, origin_sidecar_path) or None when unusable."""
    from app.worker.existing_subs import extract_embedded, strip_sdh
    from app.worker.subtitle_verify import parse_srt
    if cand.kind == "sidecar":
        path, origin = cand.path, cand.path
    else:
        path = f"{_LOG_DIR}/{job_id}.embedded{cand.stream_index}.srt"
        origin = None
        if not extract_embedded(job.file_path, cand.stream_index, path):
            return None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cues = strip_sdh(parse_srt(f.read()))
    except OSError:
        return None
    return (cues, origin) if cues else None


def _candidate_language(cleaned: list[dict], cand_language: str | None,
                        job: Job) -> tuple[str | None, str | None]:
    """``(language, None)`` when acceptable, ``(None, reason)`` when rejected.

    Detection from the text wins over the filename/container tag. With an
    explicit source hint, a candidate matching neither the hint nor the
    target is rejected — the user asked for something else. With source
    "auto" any confidently-detected language is acceptable: it is a valid
    translation source, and the verification + audio-sync gates still
    protect against wrong-cut or garbage tracks."""
    from app.worker.langid import detect_language
    sample = " ".join(c.get("text", "") for c in cleaned[:200])
    detected = detect_language(sample)
    lang = (detected[0] if detected else None) or normalize_lang_code(cand_language) or None
    if not lang:
        return None, "language could not be detected"
    hint = job.source_language if job.source_language not in (None, "", "auto") else None
    if hint is None:
        return lang, None
    acceptable = {normalize_lang_code(v) for v in (hint, job.target_language) if v}
    if lang not in acceptable:
        return None, (f"detected language '{lang}' matches neither "
                      f"source '{hint}' nor target '{job.target_language}'")
    return lang, None


def _existing_subs_verdict(cleaned: list[dict], duration: float | None,
                           speech_regions) -> str:
    """pass/warn/fail for a candidate: full structural+heuristic battery plus
    the VAD audio-sync check (catches subs made for a different cut). No LLM."""
    from app.worker.subtitle_verify import aggregate
    from app.worker.sync_check import sync_check
    result = _verify_subtitles(_segments_to_srt(cleaned), video_duration=duration,
                               model_cfg=None)
    checks = list(result.get("report", {}).get("checks", []))
    checks.append(sync_check(cleaned, speech_regions))
    return aggregate(checks)["status"]


def _try_existing_subs(
    job: Job, job_id: str, log_path: str, speech_regions,
) -> dict | None:
    """Discovery + verification gate. Returns an existing-cues transcription
    dict (accepted candidate) or None to proceed with ASR. Blocking (file
    reads, ffprobe/ffmpeg) — callers run it via asyncio.to_thread."""
    from app.worker.cue_timing import apply_invariants
    from app.worker.existing_subs import (
        find_sidecar_candidates, probe_embedded_candidates, rank_candidates)
    if not _existing_subs_enabled(job):
        return None
    exclude = ({_output_srt_path(job.file_path, job.target_language)}
               if job.target_language else set())
    candidates = rank_candidates(
        find_sidecar_candidates(job.file_path, exclude)
        + probe_embedded_candidates(job.file_path),
        job.source_language, job.target_language,
    )[:_EXISTING_SUBS_MAX_CANDIDATES]
    if not candidates:
        return None
    duration = _probe_duration(job.file_path)
    for cand in candidates:
        loaded = _candidate_cues(job, job_id, cand)
        if loaded is None:
            continue
        cleaned, origin = loaded
        lang, reject_reason = _candidate_language(cleaned, cand.language, job)
        if lang is None:
            _write_log(log_path, "INFO", job_id,
                       f"existing subtitles skipped ({cand.describe()}): "
                       f"{reject_reason}")
            continue
        status = _existing_subs_verdict(cleaned, duration, speech_regions)
        if status not in ("pass", "warn"):
            _write_log(log_path, "INFO", job_id,
                       f"existing subtitles rejected ({cand.describe()}): "
                       f"verification {status}")
            continue
        _write_log(log_path, "INFO", job_id,
                   f"Using existing subtitles ({cand.describe()}, {lang}, "
                   f"verification {status}) — skipping transcription")
        return {"language": lang, "existing_cues": apply_invariants(cleaned),
                "origin_path": origin}
    return None


def _langs_equal(a: str | None, b: str | None) -> bool:
    na, nb = normalize_lang_code(a) or None, normalize_lang_code(b) or None
    return na is not None and na == nb


def _load_source_srt_cues(job: Job, log_path: str) -> list[dict] | None:
    """Cues from job.source_srt_path, or None to run the normal ASR pipeline.

    Best-effort: a missing/unreadable/empty file logs a warning and falls
    back to transcription — the fast path is an optimization, never a new
    failure mode."""
    path = getattr(job, "source_srt_path", None)
    if not path:
        return None
    from app.worker.subtitle_verify import parse_srt
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            cues = parse_srt(f.read())
    except OSError:
        cues = []
    if not cues:
        _write_log(log_path, "WARNING", job.id,
                   f"source SRT unusable ({path}) — falling back to transcription")
        return None
    _write_log(log_path, "INFO", job.id,
               f"Starting from existing source subtitles ({len(cues)} cues) — "
               "skipping audio extraction and transcription")
    return cues


async def _source_cues_stage(
    job: Job, job_id: str, audio_path: str, log_path: str,
    redis_client: aioredis.Redis,
) -> tuple[Job, list[dict] | None, str | None, dict | None]:
    """Produce the source cues: from job.source_srt_path when set (fast
    re-translate / existing-subtitles path), else extract + transcribe.
    Returns (job, src_cues, source_srt, cancel_result); when cancel_result
    is not None the pipeline must return it."""
    srt_cues = _load_source_srt_cues(job, log_path)
    if srt_cues is not None:
        job = await _update_job(job_id, progress=60)
        return job, srt_cues, job.source_srt_path, None
    transcription, cancelled = await _obtain_transcription(
        job, job_id, audio_path, log_path, redis_client)
    if cancelled is not None:
        return job, None, None, cancelled
    if (result := await _check_cancel_after(job_id, log_path, "transcribe")):
        return job, None, None, result
    job, src_cues, source_srt = await _source_srt_phase(
        job_id, transcription, log_path, redis_client)
    return job, src_cues, source_srt, None


async def _obtain_transcription(
    job: Job, job_id: str, audio_path: str, log_path: str,
    redis_client: aioredis.Redis,
) -> tuple[dict | None, dict | None]:
    """Extract + VAD + transcribe, or resume from a persisted checkpoint
    (2026-07 audit WS9). Returns ``(transcription, cancel_result)`` — when
    the job was cancelled mid-phase, ``cancel_result`` carries the pipeline
    return value and ``transcription`` is None."""
    checkpoint = _load_transcription_checkpoint(job_id)
    if checkpoint is not None:
        _write_log(log_path, "INFO", job_id,
                   "Resuming from transcription checkpoint — "
                   "skipping extraction and transcription")
        await _update_job(job_id,
                          source_language=checkpoint.get("language"),
                          progress=60)
        return checkpoint, None

    await _extract_audio(job, job_id, audio_path, log_path, redis_client)
    if (result := await _check_cancel_after(job_id, log_path, "extract")):
        return None, result
    speech_regions = await _run_vad(job_id, audio_path, log_path)

    # Existing-subtitle gate: a shipped track that passes verification
    # (including audio-sync against the VAD regions) replaces ASR outright.
    existing = await asyncio.to_thread(
        _try_existing_subs, job, job_id, log_path, speech_regions)
    if existing is not None:
        await _update_job(job_id, source_language=existing["language"], progress=60)
        _save_transcription_checkpoint(job_id, existing)
        return existing, None

    transcription = await _transcribe(job, job_id, audio_path, log_path,
                                      redis_client, speech_regions)
    transcription = await _second_pass_recover(
        job, job_id, audio_path, log_path, transcription, speech_regions)
    _save_transcription_checkpoint(job_id, transcription)
    return transcription, None


def _second_pass_enabled() -> bool:
    return os.environ.get("SUBGEN_DISABLE_SECOND_PASS", "").lower() not in ("1", "true", "yes")


def _recover_gap_blocking(
    audio_path: str, gap: tuple[float, float],
    url: str, model: str, api_key: str | None, language: str | None,
) -> list[dict]:
    """Extract one enhanced clip, re-transcribe it, return segments shifted
    back onto the full-file timeline. Blocking; run in an executor. The clip
    lives in a mkstemp-created file (unpredictable name, 0600) for the
    duration of the call."""
    import tempfile
    from app.worker.second_pass import CLIP_PAD_SECONDS, ENHANCE_FILTER, offset_segments
    import ffmpeg
    start = max(0.0, gap[0] - CLIP_PAD_SECONDS)
    duration = (gap[1] + CLIP_PAD_SECONDS) - start
    fd, clip_path = tempfile.mkstemp(suffix=".wav", prefix="subgen-gap-")
    os.close(fd)
    (ffmpeg
     .input(audio_path, ss=start, t=duration)
     .output(clip_path, af=ENHANCE_FILTER, acodec="pcm_s16le", ac=1, ar="16000")
     .overwrite_output()
     .run(capture_stdout=True, capture_stderr=True))
    try:
        result = _run_transcription_remote_blocking(
            clip_path, url, model, api_key, language_hint=language)
    finally:
        try:
            os.remove(clip_path)
        except OSError:
            pass
    return offset_segments(_reduce_response_segments(result.get("segments") or []), start)


async def _second_pass_recover(
    job: Job, job_id: str, audio_path: str, log_path: str,
    transcription: dict, speech_regions: list[tuple[float, float]] | None,
) -> dict:
    """Re-attack VAD-speech spans the first pass left empty (faint dialogue:
    phone calls, whispers) with aggressive enhancement. Best-effort: any
    failure leaves the first-pass transcription untouched."""
    from app.worker.second_pass import find_speech_gaps, merge_recovered
    # A bare segment list is the defensive/legacy shape build_source_cues
    # tolerates — nothing to enrich safely, pass it through.
    if not _second_pass_enabled() or not isinstance(transcription, dict):
        return transcription
    segments = transcription.get("segments") or []
    gaps = find_speech_gaps(speech_regions, segments)
    if not gaps:
        return transcription
    b = _job_backend(job)
    url, model = b.get("transcription_api_url") or "", b.get("transcription_model") or "large-v3"
    if not url:
        return transcription
    _write_log(log_path, "INFO", job_id,
               f"Second pass: {len(gaps)} speech region(s) without text — "
               "re-transcribing with enhancement")
    recovered: list[dict] = []
    language = transcription.get("language")
    for gap in gaps:
        try:
            segs = await asyncio.to_thread(
                _recover_gap_blocking, audio_path, gap, url, model,
                b.get("transcription_api_key"), language)
        except Exception as e:  # noqa: BLE001
            _write_log(log_path, "WARNING", job_id,
                       f"second-pass clip {gap[0]:.1f}-{gap[1]:.1f}s failed "
                       f"({type(e).__name__}) — skipping")
            continue
        filtered = filter_segments(segs, speech_regions=None)
        recovered.extend(filtered.segments)
    if not recovered:
        _write_log(log_path, "INFO", job_id, "Second pass recovered nothing")
        return transcription
    merged = merge_recovered(segments, recovered)
    _write_log(log_path, "INFO", job_id,
               f"Second pass recovered {len(merged) - len(segments)} segment(s) "
               f"from {len(gaps)} gap(s)")
    return {**transcription, "segments": merged}


async def _source_srt_phase(
    job_id: str, transcription: dict, log_path: str, redis_client: aioredis.Redis,
) -> tuple[Job, list[dict], str]:
    """Build and write the source-language SRT: re-fetch the job (for the
    detected source_language set by _transcribe), re-segment into
    speech-aligned reading-speed-bounded cues, optionally snap to shot
    changes, write atomically."""
    job = await _fetch_job(job_id)
    existing = transcription.get("existing_cues") if isinstance(transcription, dict) else None
    if existing is not None:
        # Human-authored cues: already well-formed, so no re-segmentation or
        # shot-snapping. Write our canonical source SRT unless the accepted
        # sidecar already IS that file — never rewrite the user's own copy.
        canonical = _output_srt_path(job.file_path, job.source_language)
        if transcription.get("origin_path") == canonical:
            source_srt = canonical
            await _update_job(job_id, source_srt_path=canonical)
        else:
            source_srt = await _write_srt_for(
                job, job_id, existing, job.source_language, log_path, redis_client)
            await _update_job(job_id, source_srt_path=source_srt)
        return job, existing, source_srt
    src_cues = build_source_cues(transcription)
    src_cues = await _maybe_snap_to_shots(job, job_id, src_cues, log_path)
    source_srt = await _write_srt_for(
        job, job_id, src_cues, job.source_language, log_path, redis_client)
    return job, src_cues, source_srt


async def _deliverable_phase(
    job: Job, job_id: str, src_cues: list[dict], source_srt: str,
    log_path: str, redis_client: aioredis.Redis,
):
    """Translate when a different target language is wanted; otherwise the
    source SRT is the deliverable (an accepted existing track can already be
    in the target language). Returns the SRT path, or the cancel result dict
    when translation was cancelled mid-phase."""
    if job.target_language and not _langs_equal(job.source_language, job.target_language):
        return await _translate_phase(job, job_id, src_cues, log_path, redis_client)
    if job.target_language:
        _write_log(log_path, "INFO", job_id,
                   "Source subtitles already in the target language — "
                   "no translation needed")
    return source_srt


async def _complete_pipeline(
    job_id: str, srt_path: str, log_path: str, redis_client: aioredis.Redis
) -> dict:
    """Terminal success path: CAS the completed status (a racing cancel wins),
    clear resume artifacts, then the fire-and-forget tail — Jellyfin refresh
    and best-effort verification — neither of which may fail the job."""
    job = await _complete_job_if_processing(
        job_id, status=JobStatus.completed, phase=JobPhase.done, progress=100,
        completed_at=_utcnow(),
    )
    if job is None:
        # A cancel won the race against the terminal write.
        _write_log(log_path, "INFO", job_id, "Job cancelled during final write — not completing")
        _clear_job_artifacts(job_id)
        return {"status": JobStatus.cancelled, "srt_path": srt_path}
    _clear_job_artifacts(job_id)
    _write_log(log_path, "INFO", job_id, f"Job completed successfully — {srt_path}")
    await _publish_event(redis_client, job)

    # fire-and-forget Jellyfin library refresh. Never raises;
    # failures stay out of the worker's success path.
    await _trigger_jellyfin_refresh(job_id, log_path, redis_client)

    # Post-completion verification — best-effort, never re-raises. Only this
    # fresh-generation path may trigger the free auto-retry; a manual
    # re-verify (verify_subtitles task) never does.
    try:
        await run_verification(job_id, allow_auto_retry=True)
    except Exception:  # noqa: BLE001
        _write_log(log_path, "WARNING", job_id,
                   "post-completion verification failed (non-fatal)")

    return {"status": JobStatus.completed, "srt_path": srt_path}


async def _async_pipeline(job_id: str) -> dict:
    job = await _fetch_job(job_id)
    if job is None:
        return {"status": JobStatus.failed, "srt_path": None}

    # If the API cancelled the job before the worker picked it up, exit cleanly.
    if job.status == JobStatus.cancelled:
        return {"status": JobStatus.cancelled, "srt_path": None}

    # Idempotency guard (2026-07 audit R4): only a queued row may start the
    # pipeline. A redelivered message for a completed/failed job (acks_late +
    # visibility-timeout redelivery, duplicate dispatch) must be a no-op, and
    # status=processing means another worker owns it — orphan recovery flips
    # crashed rows back to queued before re-dispatching.
    if job.status != JobStatus.queued:
        return {"status": job.status, "srt_path": None}

    log_path = f"{_LOG_DIR}/{job_id}.log"
    os.makedirs(_LOG_DIR, exist_ok=True)

    redis_client = aioredis.from_url(app_settings.redis_url)
    try:
        job = await _update_job(job_id, status=JobStatus.processing, log_path=log_path)
        _write_log(log_path, "INFO", job_id, "Job started — status=processing")
        await _publish_event(redis_client, job)

        audio_path = f"/tmp/{job_id}.wav"
        try:
            job, src_cues, source_srt, cancelled = await _source_cues_stage(
                job, job_id, audio_path, log_path, redis_client)
            if cancelled is not None:
                return cancelled

            srt_path = await _deliverable_phase(
                job, job_id, src_cues, source_srt, log_path, redis_client)
            if isinstance(srt_path, dict):  # cancelled mid-phase
                return srt_path

            return await _complete_pipeline(job_id, srt_path, log_path, redis_client)

        except _JobCancelled:
            job = await _fetch_job(job_id)
            if job is not None:
                await _publish_event(redis_client, job)
            return {"status": JobStatus.cancelled, "srt_path": None}
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


# ---------------------------------------------------------------------------
# Post-completion subtitle verification
# ---------------------------------------------------------------------------

async def _publish_job_update_safe(job: Job) -> None:
    """Best-effort publish using its own Redis connection. Never raises."""
    from app.services.job_events import publish_job_update
    from redis.exceptions import RedisError
    try:
        await publish_job_update(job)
    except (RedisError, OSError):
        pass


def _verification_srt_paths(job: Job) -> tuple[list[str], str | None]:
    """Return ([primary SRT to verify], source SRT path for faithfulness | None).

    Primary = target SRT when translated, else source SRT."""
    src = _output_srt_path(job.file_path, job.source_language) if job.source_language else None
    if job.target_language:
        return [_output_srt_path(job.file_path, job.target_language)], src
    return ([src] if src else []), None


def _verification_model_cfg(job: Job) -> dict | None:
    """Build LLM model_cfg from the job's backend profile, or None if unconfigured."""
    try:
        b = _job_backend(job)
    except RuntimeError:
        return None
    model = b.get("translation_model")
    if not model:
        return None
    base_url, api_key, mapped = _resolve_litellm_target(
        b.get("translation_provider"), model,
        b.get("translation_api_url"), b.get("translation_api_key"),
    )
    return {"mapped_model": mapped, "base_url": base_url, "api_key": api_key}


def _probe_duration(media_path: str) -> float | None:
    """Best-effort media duration (seconds) via ffprobe, for the coverage check.
    Returns None on any failure — coverage is then skipped, not failed."""
    try:
        import ffmpeg
        dur = ffmpeg.probe(media_path).get("format", {}).get("duration")
        return float(dur) if dur is not None else None
    except Exception:
        return None


def _run_verification_verdict(job: Job) -> dict:
    """Read the SRT(s) and run _verify_subtitles(). Best-effort by contract: ANY
    failure (missing file, bad profile config raising RuntimeError, LLM/parse
    error) becomes an 'error' verdict rather than raising — so a job never gets
    stranded in verification_status='running'."""
    try:
        primary, source_path = _verification_srt_paths(job)
        if not primary or not os.path.exists(primary[0]):
            return {"status": "error", "score": 0.0,
                    "report": {"summary": "no SRT found on disk", "checks": []}}
        with open(primary[0], encoding="utf-8", errors="replace") as f:
            srt_text = f.read()
        source_text = None
        if job.target_language and source_path and os.path.exists(source_path):
            with open(source_path, encoding="utf-8", errors="replace") as f:
                source_text = f.read()
        model_cfg = _verification_model_cfg(job)
        result = _verify_subtitles(srt_text, source_srt_text=source_text,
                                   video_duration=_probe_duration(job.file_path),
                                   model_cfg=model_cfg)
        return _append_worker_checks(result, srt_text, job)
    except Exception as e:  # best-effort: never strand the job in 'running'
        return {"status": "error", "score": 0.0,
                "report": {"summary": f"verification error: {type(e).__name__}", "checks": []}}


def _append_worker_checks(result: dict, srt_text: str, job: Job) -> dict:
    """Add worker-side checks (output language, audio↔subtitle sync) to a
    verify() result and re-aggregate. Extra report keys (e.g. metrics) are
    preserved. These live here rather than in subtitle_verify because they
    need worker-only dependencies (fastText model, per-job VAD data)."""
    from app.worker.subtitle_verify import aggregate, parse_srt
    from app.worker.sync_check import sync_check
    from app.worker.vad import load_regions

    cues = parse_srt(srt_text)
    extra = [
        language_check(cues, normalize_lang_code(job.target_language) or None),
        sync_check(cues, load_regions(f"{_LOG_DIR}/{job.id}.vad.json")),
    ]
    checks = list(result.get("report", {}).get("checks", [])) + extra
    agg = aggregate(checks)
    agg["report"] = {**result.get("report", {}), **agg["report"]}
    return agg


async def run_verification(job_id: str, allow_auto_retry: bool = False) -> None:
    """Async orchestration: fetch job → set running → verify → persist → publish.

    ``allow_auto_retry`` is True only on the fresh-generation path
    (_complete_pipeline); a hard fail there may queue one free regeneration."""
    job = await _fetch_job(job_id)
    if job is None:
        return
    job = await _update_job(job_id, verification_status="running")
    await _publish_job_update_safe(job)
    # The verdict does blocking I/O (file reads) + a synchronous LLM call; run it
    # off the event loop so it doesn't stall SSE/other coroutines on the worker.
    verdict = await asyncio.to_thread(_run_verification_verdict, job)
    job = await _update_job(
        job_id,
        verification_status=verdict["status"],
        verification_score=verdict["score"],
        verification_report=verdict["report"],
        verified_at=_utcnow(),
    )
    await _publish_job_update_safe(job)
    if allow_auto_retry and verdict["status"] == "fail":
        await _maybe_auto_retry(job)


# Fail-severity checks that implicate ONLY the translation stage. When every
# hard fail is in this set, the transcription was good and the retry can
# re-translate from the on-disk source SRT instead of re-running ASR.
_TRANSLATION_ONLY_FAILS = {"output_language", "alignment", "llm_coherence"}


def _fast_retry_srt(job: Job) -> str | None:
    """Source SRT path for a translation-only re-run, or None for a full one."""
    if not (job.target_language and job.source_language):
        return None
    checks = (job.verification_report or {}).get("checks", [])
    fails = {c.get("name") for c in checks if c.get("severity") == "fail"}
    if not fails or not fails <= _TRANSLATION_ONLY_FAILS:
        return None
    path = _output_srt_path(job.file_path, job.source_language)
    return path if os.path.exists(path) else None


async def _maybe_auto_retry(job: Job) -> None:
    """Queue one cost-free regeneration after a hard verification fail.

    Best-effort by contract: eligibility (cost gate, lineage cap, kill switch)
    lives in auto_retry.should_auto_retry; regenerate_job's ALREADY_ACTIVE
    guard makes a concurrent manual retry win quietly; any other failure is
    logged and swallowed — the job stays flagged exactly as before."""
    from app.worker.auto_retry import AUTO_RETRY_SOURCE_PREFIX, should_auto_retry
    if not should_auto_retry(job):
        return
    log_path = f"{_LOG_DIR}/{job.id}.log"
    from app.core.database import AsyncSessionLocal
    from app.services.job_service import RegenerateError, regenerate_job
    fast_srt = _fast_retry_srt(job)
    if fast_srt:
        # Translation-only fail: re-translate from the original's source SRT.
        retry_kwargs = {"source_srt_path": fast_srt}
    else:
        # Full re-run: clear any SRT source AND the existing-subs gate, so a
        # bad shipped track (or bad prior transcription) can't be re-picked —
        # the retry must genuinely re-transcribe.
        retry_kwargs = {"source_srt_path": None, "use_existing_subs": False}
    try:
        async with AsyncSessionLocal() as session:
            new_job = await regenerate_job(
                session, job.id, source=f"{AUTO_RETRY_SOURCE_PREFIX}{job.id}",
                **retry_kwargs)
    except RegenerateError as e:
        _write_log(log_path, "INFO", job.id, f"auto-retry skipped: {e.code}")
        return
    except Exception:  # noqa: BLE001
        _write_log(log_path, "WARNING", job.id,
                   "auto-retry failed to queue (non-fatal)")
        return
    generate_subtitles.delay(new_job.id)
    await _publish_job_update_safe(new_job)
    # Link the retry on the original's report so the UI can say "a free
    # automatic retry was started" instead of leaving a silent dead end.
    report = {**(job.verification_report or {}), "auto_retry_job_id": new_job.id}
    updated = await _update_job(job.id, verification_report=report)
    await _publish_job_update_safe(updated)
    mode = "re-translate from source SRT" if fast_srt else "full re-run"
    _write_log(log_path, "INFO", job.id,
               f"verification failed on a cost-free profile — queued automatic retry "
               f"{new_job.id} ({mode})")


@celery_app.task(name="verify_subtitles")
def verify_subtitles(job_id: str) -> None:
    asyncio.run(run_verification(job_id))
