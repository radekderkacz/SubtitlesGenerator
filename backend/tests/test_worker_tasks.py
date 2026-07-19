import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import JobStatus, JobPhase
from app.worker.cue_timing import format_cues_from_segments
from app.worker.tasks import (
    _async_pipeline,
    _compress_audio_for_remote,
    _extract_glossary_blocking,
    _format_srt_timestamp,
    _format_translation_error,
    _guard_remote_audio_size,
    _job_backend,
    _output_srt_path,
    _parse_batch_response,
    _resolve_litellm_target,
    _segments_to_srt,
    _translate_batch_blocking,
    _translate_segment_blocking,
)


@pytest.fixture(autouse=True)
def _stub_jellyfin_refresh(request):
    """happy-path pipeline tests don't seed Jellyfin settings, so
    auto-stub the refresh hop so they don't try to open a real DB session.
    Tests that exercise the refresh function directly opt out via the
    `no_jellyfin_stub` marker.
    """
    if request.node.get_closest_marker("no_jellyfin_stub") is not None:
        yield
        return
    with patch("app.worker.tasks._trigger_jellyfin_refresh", AsyncMock()):
        yield


@pytest.fixture(autouse=True)
def _stub_run_verification(request):
    """Task 7 — post-completion verification is best-effort; stub it out in
    pipeline tests that don't exercise verification directly so they don't
    need to seed SRT files or a real DB session. Tests that exercise
    run_verification directly opt out via `no_verification_stub`."""
    if request.node.get_closest_marker("no_verification_stub") is not None:
        yield
        return
    with patch("app.worker.tasks.run_verification", AsyncMock()):
        yield


def _cas_via(mock_update):
    """Route the WS5 compare-and-set completion through a test's _update_job
    mock (the mocked job is always 'processing'; the CAS race is covered by
    its own dedicated test)."""
    async def _cas(job_id, **fields):
        return await mock_update(job_id, **fields)
    return _cas


def _make_job(**kwargs):
    job = MagicMock()
    job.id = "test-job-id"
    job.status = "queued"
    job.phase = None
    job.progress = 0
    job.log_path = None
    job.error_message = None
    job.translation_provider = None
    job.translation_model = None
    job.target_language = None
    job.model_size = None
    job.file_path = "/media/test.mkv"
    job.updated_at = datetime.now(timezone.utc)
    job.verification_status = None
    job.verification_score = None
    job.verification_report = None
    job.verified_at = None
    job.source_srt_path = None
    job.use_existing_subs = False
    for k, v in kwargs.items():
        setattr(job, k, v)
    return job


# ---------------------------------------------------------------------------
# AC2 + AC3: happy path — processing → completed with events published
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_happy_path(tmp_path):
    """Job found → status=processing → status=completed; events published; log file created."""
    job = _make_job()
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    assert result["srt_path"] == "/tmp/test.srt"

    statuses = [u["status"] for u in updated if "status" in u]
    assert JobStatus.processing in statuses
    assert JobStatus.completed in statuses

    assert mock_redis.publish.call_count == 2   # one for processing, one for completed
    assert mock_redis.aclose.called

    log_file = tmp_path / "test-job-id.log"
    assert log_file.exists()
    assert "[job:test-job-id]" in log_file.read_text()


# ---------------------------------------------------------------------------
# AC2: job not found — returns failed immediately, no exception, no event
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_job_not_found():
    """Fetch returns None → returns failed dict without raising or publishing."""
    async def mock_fetch(job_id):
        return None

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("missing-id")

    assert result == {"status": JobStatus.failed, "srt_path": None}
    mock_redis.publish.assert_not_called()


# ---------------------------------------------------------------------------
# AC6: exception in pipeline → status=failed, error_message set, event published, re-raised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_exception_marks_job_failed(tmp_path):
    """Exception during processing → job status=failed, error_message set, failure event published, exception re-raised."""
    job = _make_job()

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        if fields.get("status") == JobStatus.completed:
            raise RuntimeError("disk full")
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        with pytest.raises(RuntimeError, match="disk full"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed
    assert "disk full" in job.error_message
    assert mock_redis.publish.called
    assert mock_redis.aclose.called


# ---------------------------------------------------------------------------
# AC1–3, AC5–6: audio extraction happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_audio_extraction_happy_path(tmp_path):
    """ffmpeg succeeds → phase=extracting at progress=5, then progress=15, then completed."""
    job = _make_job(file_path="/media/movies/Film.mkv")
    settings = MagicMock()
    settings.nas_mount_path = "/media"
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()
    mock_ffmpeg_module = MagicMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch.dict("sys.modules", {"ffmpeg": mock_ffmpeg_module}):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    phases = [u.get("phase") for u in updated if "phase" in u]
    assert JobPhase.extracting in phases
    progress_vals = [u.get("progress") for u in updated if "progress" in u]
    assert 5 in progress_vals
    assert 15 in progress_vals
    mock_ffmpeg_module.input.assert_called_once()


# ---------------------------------------------------------------------------
# AC4–5: ffmpeg failure → job failed, temp file cleaned up
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_ffmpeg_failure_marks_job_failed(tmp_path):
    """ffmpeg Error → job status=failed with ffmpeg error message; temp file removed."""
    job = _make_job(file_path="/media/Film.mkv")
    settings = MagicMock()
    settings.nas_mount_path = "/media"

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    class FfmpegError(Exception):
        def __init__(self, cmd, stdout, stderr):
            self.cmd = cmd
            self.stdout = stdout
            self.stderr = stderr

    mock_ffmpeg_module = MagicMock()
    mock_ffmpeg_module.Error = FfmpegError
    # WS7: extraction selects a stream and builds via module-level
    # ffmpeg.output(src, ...) rather than input(...).output(...)
    mock_ffmpeg_module.output.return_value.overwrite_output.return_value.run.side_effect = (
        FfmpegError("ffmpeg", b"", b"Invalid data found")
    )

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch.dict("sys.modules", {"ffmpeg": mock_ffmpeg_module}):
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed
    assert "ffmpeg failed" in job.error_message
    assert not os.path.exists("/tmp/test-job-id.wav")


# ---------------------------------------------------------------------------
# AC6: path traversal → job failed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_path_traversal_marks_job_failed(tmp_path):
    """Path outside NAS mount → job status=failed with clear error message."""
    job = _make_job(file_path="/etc/passwd")
    settings = MagicMock()
    settings.nas_mount_path = "/media"

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch.dict("sys.modules", {"ffmpeg": MagicMock()}):
        with pytest.raises(RuntimeError, match="outside NAS mount root"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed
    assert "outside NAS mount root" in job.error_message


# ---------------------------------------------------------------------------
# AC1–4, AC7–8: transcription happy path — CUDA, alignment succeeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_translation_skipped_when_no_provider(tmp_path):
    """job.target_language is None (no translation requested) → translation phase skipped, no phase=translating event."""
    job = _make_job(file_path="/media/Film.mkv", source_language="en", translation_provider=None, target_language=None)
    settings = MagicMock()
    settings.nas_mount_path = "/media"
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    phases = [u.get("phase") for u in updated if "phase" in u]
    assert JobPhase.translating not in phases
    progress_vals = [u.get("progress") for u in updated if "progress" in u]
    assert 65 not in progress_vals


# ---------------------------------------------------------------------------
# AC2–4, AC7: translation happy path — ollama, segments mutated, progress 65→80
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_translation_happy_path(tmp_path):
    """provider=ollama, 2 segments translated, phase=translating, progress 65→80, ollama mapping verified."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="fr",
        translation_provider="ollama",
        translation_model="llama3",
        target_language="en",
        backend_profile={
            "translation_provider": "ollama",
            "translation_model": "llama3",
            "translation_api_url": "http://ollama:11434",
            "translation_api_key": None,
        },
    )
    settings = MagicMock()
    settings.nas_mount_path = "/media"
    updated = []
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Bonjour"},
        {"start": 1.0, "end": 2.0, "text": "Merci"},
    ]

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()

    # Mock httpx.Client used by _translate_segment_blocking. Each post call
    # returns content "Hello".
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "Hello"}}]}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    mock_write_srt_for = AsyncMock(side_effect=lambda job, job_id, segs, lang, log_path, redis_client: f"/media/Film.{lang}.srt")

    # The glossary extraction call is exercised in dedicated tests; stub it
    # here so this test stays focused on per-segment translation behavior
    # (otherwise `httpx.Client.post.call_count` and the call-order assertions
    # below would have to account for the +1 upfront extraction call).
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=segments)), \
         patch("app.worker.tasks._write_srt_for", mock_write_srt_for), \
         patch("app.worker.tasks._extract_glossary_blocking", return_value=([], {})), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch("httpx.Client", return_value=mock_client):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    # Dual-write: source SRT (fr) first, then target SRT (en); srt_path is the target.
    assert mock_write_srt_for.call_count == 2
    assert mock_write_srt_for.call_args_list[0].args[3] == "fr"   # source lang
    assert mock_write_srt_for.call_args_list[1].args[3] == "en"   # target lang
    assert result["srt_path"] == "/media/Film.en.srt"
    phases = [u.get("phase") for u in updated if "phase" in u]
    assert JobPhase.translating in phases
    progress_vals = [u.get("progress") for u in updated if "progress" in u]
    assert 65 in progress_vals
    assert 80 in progress_vals
    # Batched translation: 2 segments go in one chunk (TRANSLATE_BATCH_SIZE=10).
    # The mock returns non-numbered "Hello" so _parse_batch_response returns None
    # → per-cue fallback fires (2 _translate_segment_blocking calls). All calls
    # go to the Ollama endpoint with the llama3 model and no Authorization header.
    assert mock_client.post.call_count >= 2
    for call in mock_client.post.call_args_list:
        # Ollama → {api_url}/v1/chat/completions; the litellm ``ollama/`` prefix
        # is stripped before sending to the upstream endpoint.
        assert call.args[0] == "http://ollama:11434/v1/chat/completions"
        assert call.kwargs["json"]["model"] == "llama3"
        assert "Authorization" not in call.kwargs["headers"]


# ---------------------------------------------------------------------------
# AC5, AC6: provider error → job failed with actionable message; api_key never logged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_translation_provider_error_marks_job_failed(tmp_path):
    """litellm raises ConnectionError → job fails with provider+model+exception class; api_key not in error."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="fr",
        translation_provider="openai",
        translation_model="gpt-4",
        target_language="en",
        backend_profile={
            "translation_provider": "openai",
            "translation_model": "gpt-4",
            "translation_api_url": None,
            "translation_api_key": "sk-secret",
        },
    )
    settings = MagicMock()
    settings.nas_mount_path = "/media"

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    # httpx.Client.post always raises builtin ConnectionError — classified
    # terminal (not an httpx transient class) so it fails fast and surfaces
    # with its own class name (WS3: no more blind 3x retry + rewrap).
    mock_client = MagicMock()
    mock_client.post.side_effect = ConnectionError("connection refused")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0.0, "end": 1.0, "text": "Bonjour."}])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch("httpx.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match=r"Translation failed \(openai / gpt-4\): ConnectionError"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed
    assert "Translation failed" in job.error_message
    assert "openai" in job.error_message
    assert "gpt-4" in job.error_message
    # WS3: the real exception class is surfaced (fail-fast classification);
    # the original ConnectionError is preserved as the chained ``__cause__``.
    assert "ConnectionError" in job.error_message
    assert "sk-secret" not in job.error_message


# ---------------------------------------------------------------------------
# AC3: no model configured → fail fast before any LLM call
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_translation_no_model_configured_fails_fast(tmp_path):
    """translation_provider set but model is null in the backend snapshot → RuntimeError before any LLM call."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="en",
        translation_provider="ollama",
        translation_model=None,
        target_language="pl",
        backend_profile={
            "translation_provider": "ollama",
            "translation_model": None,
            "translation_api_url": "http://ollama:11434",
            "translation_api_key": None,
        },
    )
    settings = MagicMock()
    settings.nas_mount_path = "/media"

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"text": "x"}])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        with pytest.raises(RuntimeError, match="no model configured"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed


# ---------------------------------------------------------------------------
# AC8: no target_language → fail fast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_translation_no_target_language_skips_translate(tmp_path):
    """target_language is None → translation skipped regardless of provider; job completes with source SRT only."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="en",
        translation_provider="openai",
        translation_model="gpt-4",
        target_language=None,
    )
    settings = MagicMock()
    settings.nas_mount_path = "/media"

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()
    mock_write_srt_for = AsyncMock(return_value="/tmp/Film.en.srt")

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"text": "x"}])), \
         patch("app.worker.tasks._write_srt_for", mock_write_srt_for), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    assert result["srt_path"] == "/tmp/Film.en.srt"
    # Exactly one write: source SRT only
    assert mock_write_srt_for.call_count == 1
    assert mock_write_srt_for.call_args_list[0].args[3] == "en"


@pytest.mark.asyncio
async def test_pipeline_translates_with_real_sp2_job_state(tmp_path):
    """REGRESSION (final-review CRITICAL): a real SP-2 enqueued job has the
    legacy `translation_provider` ORM column = None — translation config
    lives ONLY in backend_profile. _translate must still run translation
    (it was gating on the dead column → translating jobs silently produced
    only the source SRT). Reproduce the real production state and assert
    _run_translation is actually invoked + a target SRT is written."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="en",
        translation_provider=None,   # real SP-2 state: ORM column unset
        translation_model=None,
        target_language="pl",
        backend_profile={
            "translation_provider": "ollama",
            "translation_model": "llama3",
            "translation_api_url": "http://ollama:11434",
            "translation_api_key": None,
        },
    )

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()
    mock_run_translation = AsyncMock()
    mock_write_srt_for = AsyncMock(
        side_effect=lambda job, job_id, segs, lang, log_path, redis_client: f"/media/Film.{lang}.srt"
    )

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0.0, "end": 1.0, "text": "Hi"}])), \
         patch("app.worker.tasks._run_translation", mock_run_translation), \
         patch("app.worker.tasks._write_srt_for", mock_write_srt_for), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    # The whole point: translation actually ran despite the dead ORM column.
    assert mock_run_translation.await_count == 1
    # Dual SRT: source (en) then target (pl); final path is the target.
    langs = [c.args[3] for c in mock_write_srt_for.call_args_list]
    assert langs == ["en", "pl"]
    assert result["srt_path"] == "/media/Film.pl.srt"


# ---------------------------------------------------------------------------
# AC3: provider mapping helper unit tests
# ---------------------------------------------------------------------------

def test_format_translation_error_surfaces_import_module_name():
    """ImportError/ModuleNotFoundError messages come from CPython's import
    machinery (the module name) and are credential-free, so the actionable
    'which module' detail MUST be surfaced. This is exactly what was lost
    on job 99bdab7a (bare 'ModuleNotFoundError', module name unknowable)."""
    msg = _format_translation_error(
        "ollama", "qwen3.6:35b", ModuleNotFoundError("No module named 'tiktoken'")
    )
    assert "Translation failed (ollama / qwen3.6:35b)" in msg
    assert "ModuleNotFoundError" in msg
    assert "tiktoken" in msg  # the actionable detail is preserved


def test_format_translation_error_non_import_never_leaks_message():
    """Security invariant: provider/HTTP exceptions can embed the API key
    (URL-encoded / prefixed / whitespace-padded — substring redaction is
    unreliable). For any non-ImportError, ONLY the class name is surfaced,
    never str(e)."""
    leaky = RuntimeError("401 Unauthorized https://api?key=sk-SECRET-9999")
    msg = _format_translation_error("openai", "gpt-4", leaky)
    assert msg == "Translation failed (openai / gpt-4): RuntimeError"
    assert "SECRET" not in msg and "sk-" not in msg


def test_resolve_litellm_target_google():
    """google → ('', api_key, 'gemini/{model}')."""
    base_url, api_key, mapped = _resolve_litellm_target(
        "google", "gemini-pro", api_url=None, api_key="goog-key"
    )
    assert base_url is None
    assert api_key == "goog-key"
    assert mapped == "gemini/gemini-pro"


def test_resolve_litellm_target_custom():
    """custom → (api_url, api_key, 'openai/{model}')."""
    base_url, api_key, mapped = _resolve_litellm_target(
        "custom", "mixtral", api_url="https://api.example.com/v1", api_key="sk-x"
    )
    assert base_url == "https://api.example.com/v1"
    assert api_key == "sk-x"
    assert mapped == "openai/mixtral"


def test_resolve_litellm_target_custom_requires_api_url():
    """custom without api_url → RuntimeError fail-fast (prevents silent fallback to OpenAI)."""
    with pytest.raises(RuntimeError, match="custom translation provider requires translation_api_url"):
        _resolve_litellm_target("custom", "mixtral", api_url=None, api_key="sk-x")


def test_resolve_litellm_target_ollama_passes_api_key_when_provided():
    """ollama → (api_url, api_key, 'ollama/{model}') — api_key passed through for gated Ollama deployments."""
    base_url, api_key, mapped = _resolve_litellm_target(
        "ollama", "llama3", api_url="http://ollama:11434", api_key="bearer-token"
    )
    assert base_url == "http://ollama:11434"
    assert api_key == "bearer-token"
    assert mapped == "ollama/llama3"


def test_resolve_litellm_target_unknown_provider():
    """unknown provider → RuntimeError."""
    with pytest.raises(RuntimeError, match="Unknown translation provider"):
        _resolve_litellm_target("foo", "bar", api_url=None, api_key=None)


def test_resolve_litellm_target_openrouter():
    """openrouter → (None, api_key, 'openrouter/{model}'). OpenRouter is a
    fan-out gateway: the model id (e.g. ``anthropic/claude-3.5-sonnet``)
    is its own namespaced string, NOT a URL. The ``openrouter/`` prefix
    tells the endpoint resolver to POST to openrouter.ai instead of
    OpenAI/Ollama."""
    base_url, api_key, mapped = _resolve_litellm_target(
        "openrouter",
        "anthropic/claude-3.5-sonnet",
        api_url=None,
        api_key="or-sk-abc",
    )
    assert base_url is None
    assert api_key == "or-sk-abc"
    assert mapped == "openrouter/anthropic/claude-3.5-sonnet"


def test_resolve_litellm_target_openrouter_with_simple_model_id():
    """A model id with no provider/model slash also passes through unchanged
    — OpenRouter accepts simple ids like ``gpt-4o-mini`` for some routes."""
    _, _, mapped = _resolve_litellm_target(
        "openrouter", "gpt-4o-mini", api_url=None, api_key="or-sk-abc"
    )
    assert mapped == "openrouter/gpt-4o-mini"


# ---------------------------------------------------------------------------
# Glossary extraction (long-range proper-noun consistency)
# ---------------------------------------------------------------------------

def _glossary_mock_client(payload_content: str):
    """Build a MagicMock httpx.Client that returns `payload_content` as the
    chat completion's message content on every POST."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": payload_content}}]}
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)
    return mock_client


def test_extract_glossary_parses_raw_json_array():
    """Happy path: model returns ``["Spider", "Pandora", "Na'vi"]`` verbatim."""
    mock_client = _glossary_mock_client('["Spider", "Pandora", "Na\'vi"]')
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking(
            "Spider, Pandora, Na'vi", "ollama/llama3", "http://ollama:11434", None
        )
    assert out == ["Spider", "Pandora", "Na'vi"]


def test_extract_glossary_strips_markdown_code_fences():
    """Many local models wrap JSON in ```json ... ``` — must be tolerated."""
    fenced = '```json\n["Jake", "Neytiri"]\n```'
    mock_client = _glossary_mock_client(fenced)
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("Jake and Neytiri.", "ollama/x", "http://x", None)
    assert out == ["Jake", "Neytiri"]


def test_extract_glossary_tolerates_preamble_before_array():
    """Sometimes a model adds 'Here are the proper nouns: [...]'.
    Extract the bracketed array even with text before it."""
    payload = 'Here are the proper nouns: ["Spider", "Pandora"]. Hope this helps!'
    mock_client = _glossary_mock_client(payload)
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == ["Spider", "Pandora"]


def test_extract_glossary_deduplicates_preserving_first_occurrence_order():
    """Models occasionally repeat a term (e.g. 'Spider' appears multiple
    times in the transcript). Dedupe but keep order so the glossary block
    is deterministic across runs of the same input."""
    mock_client = _glossary_mock_client('["Spider", "Pandora", "Spider", "Jake"]')
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == ["Spider", "Pandora", "Jake"]


def test_extract_glossary_recovers_inner_array_when_model_wraps_in_object():
    """Model wraps the array in ``{"names": [...]}`` instead of returning a raw
    array. The first ``[`` / last ``]`` heuristic recovers the inner array —
    a small lenience that pays for itself the first time a model goes off-spec.
    Top-level scalar / null / number outputs still produce ``[]`` because there
    are no brackets to find."""
    mock_client = _glossary_mock_client('{"names": ["Spider"]}')
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == ["Spider"]


def test_extract_glossary_returns_empty_on_scalar_output():
    """If the model returns a plain string / number / null without any
    bracketed array, fall back to empty list. Translation still proceeds."""
    mock_client = _glossary_mock_client("I cannot do that.")
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == []


def test_extract_glossary_returns_empty_on_malformed_json():
    """Trailing comma, unclosed bracket, garbage — fall back to empty list."""
    mock_client = _glossary_mock_client('[Spider, Pandora,')
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == []


def test_extract_glossary_returns_empty_on_network_error():
    """ConnectionError on every retry → fall back gracefully. The whole
    point of the helper's try/except is that the per-segment translation
    pipeline never fails because of glossary issues."""
    mock_client = MagicMock()
    mock_client.post.side_effect = ConnectionError("connection refused")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)
    with patch("httpx.Client", return_value=mock_client):
        out, data = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == []
    assert data == {}


def test_extract_glossary_sends_authorization_header_when_api_key_present():
    """Same auth conventions as the per-segment translation calls — when
    an API key is configured, send it as Bearer; otherwise omit the header."""
    mock_client = _glossary_mock_client('[]')
    with patch("httpx.Client", return_value=mock_client):
        _extract_glossary_blocking(
            "…", "openai/gpt-4", None, "sk-secret"
        )
    call = mock_client.post.call_args
    headers = call.kwargs["headers"]
    assert headers.get("Authorization") == "Bearer sk-secret"


def test_extract_glossary_omits_authorization_when_no_api_key():
    mock_client = _glossary_mock_client('[]')
    with patch("httpx.Client", return_value=mock_client):
        _extract_glossary_blocking("…", "ollama/llama3", "http://ollama:11434", None)
    headers = mock_client.post.call_args.kwargs["headers"]
    assert "Authorization" not in headers


def test_extract_glossary_filters_non_string_array_items():
    """Defensive: if the model emits a mixed array, only keep strings."""
    mock_client = _glossary_mock_client('["Spider", 42, null, "Pandora", {"x": 1}]')
    with patch("httpx.Client", return_value=mock_client):
        out, _ = _extract_glossary_blocking("…", "ollama/x", "http://x", None)
    assert out == ["Spider", "Pandora"]


# ---------------------------------------------------------------------------
# AC7: SRT timestamp formatter (unit)
# ---------------------------------------------------------------------------

def test_format_srt_timestamp():
    assert _format_srt_timestamp(0.0) == "00:00:00,000"
    assert _format_srt_timestamp(1.234) == "00:00:01,234"
    assert _format_srt_timestamp(60.001) == "00:01:00,001"
    assert _format_srt_timestamp(3661.5) == "01:01:01,500"
    assert _format_srt_timestamp(7200.0) == "02:00:00,000"
    assert _format_srt_timestamp(-1.0) == "00:00:00,000"


def test_format_srt_timestamp_handles_nan_and_inf():
    """NaN/Inf clamped to 0 instead of raising ValueError/OverflowError."""
    assert _format_srt_timestamp(float("nan")) == "00:00:00,000"
    assert _format_srt_timestamp(float("inf")) == "00:00:00,000"
    assert _format_srt_timestamp(float("-inf")) == "00:00:00,000"


def test_format_srt_timestamp_rollover_cascades_to_minutes():
    """When ms rounds up at the minute boundary, seconds cascade into minutes (not s=60)."""
    # 59.9999995 → s=59, ms=1000 → ms=0, s=60 → s=0, m+=1
    assert _format_srt_timestamp(59.9999995) == "00:01:00,000"
    # 3599.9999995 → cascade through minutes too
    assert _format_srt_timestamp(3599.9999995) == "01:00:00,000"


# ---------------------------------------------------------------------------
# AC7: segments → SRT serializer (unit)
# ---------------------------------------------------------------------------

def test_segments_to_srt():
    segments = [
        {"start": 0.0, "end": 1.5, "text": "Hello world"},
        {"start": 2.0, "end": 4.0, "text": "  Second cue  "},
    ]
    expected = (
        "1\n00:00:00,000 --> 00:00:01,500\nHello world\n"
        "\n"
        "2\n00:00:02,000 --> 00:00:04,000\nSecond cue\n"
    )
    assert _segments_to_srt(segments) == expected


def test_segments_to_srt_preserves_intentional_line_wrap():
    """Cues are wrapped to <=2 lines by wrap_lines; SRT supports multi-line cues,
    so the writer must keep those line breaks (flattening them would silently
    discard the line-wrapping feature)."""
    segments = [
        {"start": 0.0, "end": 1.0, "text": "First line here\nSecond line here"},
    ]
    result = _segments_to_srt(segments)
    assert "First line here\nSecond line here" in result


def test_segments_to_srt_strips_lines_and_drops_blank_lines():
    """Each line is stripped and blank lines dropped so a stray double newline
    can't break cue boundaries."""
    segments = [
        {"start": 0.0, "end": 1.0, "text": "  Line one  \n\n  Line two  "},
    ]
    result = _segments_to_srt(segments)
    assert "Line one\nLine two" in result
    assert "Line one\n\n" not in result


def test_wrapped_cue_round_trips_through_srt_with_newline():
    """End-to-end seam check: a >42-char cue produced by the heuristic must
    still carry its wrap into the rendered SRT."""
    cues = format_cues_from_segments([{
        "start": 0.0, "end": 6.0,
        "text": "This single sentence is definitely longer than forty-two characters here.",
    }])
    assert "\n" in cues[0]["text"]            # the cue is wrapped to two lines
    out = _segments_to_srt(cues)
    assert cues[0]["text"] in out             # and the wrap survives into the SRT


def test_segments_to_srt_raises_on_missing_timestamps():
    """Missing start/end keys → clear RuntimeError, not opaque KeyError."""
    with pytest.raises(RuntimeError, match="missing required start/end timestamps"):
        _segments_to_srt([{"text": "no timing"}])
    with pytest.raises(RuntimeError, match="missing required start/end timestamps"):
        _segments_to_srt([{"start": 0.0, "text": "missing end"}])


# ---------------------------------------------------------------------------
# AC3: Jellyfin naming convention (unit)
# ---------------------------------------------------------------------------

def test_output_srt_path():
    assert _output_srt_path("/media/movies/Oppenheimer.2023.mkv", "en") == "/media/movies/Oppenheimer.2023.en.srt"
    assert _output_srt_path("/media/movies/Film.mp4", "pl") == "/media/movies/Film.pl.srt"
    assert _output_srt_path("/nas/show/S01E02.avi", "es") == "/nas/show/S01E02.es.srt"


# ---------------------------------------------------------------------------
# Subtitle timing: the pipeline re-segments a multi-sentence transcription
# segment into several speech-aligned cues (the reported all-at-once bug).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_resegments_multisentence_segment_into_cues(tmp_path):
    """A single multi-sentence transcription segment must become several SRT
    cues with distinct, non-overlapping windows — not one cue holding the whole
    span (the bug this feature fixes)."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()

    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock()
    settings.nas_mount_path = str(nas)

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()
    # One 9s segment, three sentences — the exact shape the live server returns.
    transcription = {
        "language": "en",
        "segments": [{"start": 0.0, "end": 9.0,
                      "text": "Look out! The bridge is closed. We have to turn back now."}],
        "words": [],
    }

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=transcription)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    srt = (nas / "Film.en.srt").read_text()
    # three cue indices -> three sentences split out of the one segment
    assert "1\n" in srt and "2\n" in srt and "3\n" in srt
    assert "Look out!" in srt
    assert "The bridge is closed." in srt
    assert "We have to turn back now." in srt
    # the last sentence must NOT start at 0 (the whole point of the fix)
    assert "3\n00:00:00,000" not in srt


# ---------------------------------------------------------------------------
# AC1, AC4, AC7: pipeline writes SRT and completes successfully
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_srt_write_happy_path(tmp_path):
    """Pipeline runs to completion; SRT file is written; status=completed, phase=done, progress=100."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()

    job = _make_job(file_path=str(video), source_language="en", target_language="en")
    settings = MagicMock()
    settings.nas_mount_path = str(nas)
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()
    segments = [
        {"start": 0.0, "end": 1.5, "text": "Hello"},
        {"start": 2.0, "end": 3.0, "text": "World"},
    ]

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=segments)), \
         patch("app.worker.tasks._translate", AsyncMock(return_value=segments)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    # target_language="en" and source_language="en" → target SRT overwrites source SRT
    expected_srt = nas / "Film.en.srt"
    assert expected_srt.exists()
    content = expected_srt.read_text()
    assert "1\n00:00:00,000 --> 00:00:01,500\nHello" in content
    assert "2\n00:00:02,000 --> 00:00:03,000\nWorld" in content

    assert result["status"] == JobStatus.completed
    assert result["srt_path"] == str(expected_srt)
    phases = [u.get("phase") for u in updated if "phase" in u]
    assert JobPhase.writing in phases
    assert JobPhase.done in phases
    progress_vals = [u.get("progress") for u in updated if "progress" in u]
    assert 90 in progress_vals
    assert 100 in progress_vals


# ---------------------------------------------------------------------------
# AC2: atomic write — temp + replace, no leftover .tmp file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_srt_write_atomic_via_temp_and_replace(tmp_path):
    """After a successful write, no `.tmp` file is left behind in the output directory."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()

    job = _make_job(file_path=str(video), source_language="en", target_language="en")
    settings = MagicMock()
    settings.nas_mount_path = str(nas)

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "ok"}])), \
         patch("app.worker.tasks._translate", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "ok"}])), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        await _async_pipeline("test-job-id")

    assert (nas / "Film.en.srt").exists()
    assert not (nas / "Film.en.srt.tmp").exists()


# ---------------------------------------------------------------------------
# AC6: os.replace overwrites existing SRT atomically
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_srt_write_rejects_path_traversal_in_language_codes(tmp_path):
    """Language codes containing '/' or '..' must fail fast — never escape NAS root."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()

    settings = MagicMock()
    settings.nas_mount_path = str(nas)

    async def mock_fetch_settings():
        return settings

    mock_redis = AsyncMock()

    # Bad target_language traversal (source is valid "en")
    for bad_lang in ("../etc/passwd", "en/../.."):
        job = _make_job(file_path=str(video), source_language="en", target_language=bad_lang)

        async def mock_update(job_id, **fields):
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        async def mock_fetch(job_id):
            return job

        with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
             patch("app.worker.tasks._fetch_job", mock_fetch), \
             patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
             patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
             patch("app.worker.tasks._extract_audio", AsyncMock()), \
             patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "x"}])), \
             patch("app.worker.tasks._translate", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "x"}])), \
             patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
            with pytest.raises(RuntimeError, match="Invalid language code"):
                await _async_pipeline("test-job-id")

    # Bad source_language traversal (no translation)
    for bad_src in ("../etc/passwd", "en/../..", "", None):
        job = _make_job(file_path=str(video), source_language=bad_src, target_language=None)

        async def mock_update(job_id, **fields):
            for k, v in fields.items():
                setattr(job, k, v)
            return job

        async def mock_fetch(job_id):
            return job

        with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
             patch("app.worker.tasks._fetch_job", mock_fetch), \
             patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
             patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
             patch("app.worker.tasks._extract_audio", AsyncMock()), \
             patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "x"}])), \
             patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
            with pytest.raises(RuntimeError, match="Invalid language code"):
                await _async_pipeline("test-job-id")


@pytest.mark.asyncio
async def test_pipeline_srt_write_overwrites_existing(tmp_path):
    """An existing SRT at the output path is overwritten atomically with the new content."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()
    existing = nas / "Film.en.srt"
    existing.write_text("OLD CONTENT — must be replaced")

    job = _make_job(file_path=str(video), source_language="en", target_language="en")
    settings = MagicMock()
    settings.nas_mount_path = str(nas)

    async def mock_fetch(job_id):
        return job

    async def mock_fetch_settings():
        return settings

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "NEW"}])), \
         patch("app.worker.tasks._translate", AsyncMock(return_value=[{"start": 0, "end": 1, "text": "NEW"}])), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        await _async_pipeline("test-job-id")

    content = existing.read_text()
    assert "NEW" in content
    assert "OLD CONTENT" not in content



# ---------------------------------------------------------------------------
async def test_pipeline_aborts_when_cancelled_before_pickup(tmp_path):
    """Job arrives in DB already marked cancelled (API revoked while in queue) → exit cleanly."""
    job = _make_job()
    job.status = JobStatus.cancelled

    async def mock_fetch(job_id):
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result == {"status": JobStatus.cancelled, "srt_path": None}
    # Pipeline never opened a Redis publisher / wrote a log because it short-circuited
    mock_redis.publish.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_aborts_after_extract_when_cancelled(tmp_path):
    """User cancels mid-pipeline (after extract phase) → next _check_cancelled aborts cleanly."""
    job = _make_job()
    cancelled_job = _make_job(id=job.id, status=JobStatus.cancelled)

    fetch_calls = {"count": 0}

    async def mock_fetch(job_id):
        fetch_calls["count"] += 1
        # First call (start of pipeline) returns queued; subsequent calls (cancellation
        # checks between phases) return cancelled.
        return job if fetch_calls["count"] == 1 else cancelled_job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    mock_redis = AsyncMock()

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.cancelled
    assert result["srt_path"] is None


# ---------------------------------------------------------------------------
# Jellyfin refresh hop after SRT write
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.no_jellyfin_stub
async def test_trigger_jellyfin_refresh_skips_when_not_configured(tmp_path):
    """No URL/key → debug log, no DB write."""
    from app.worker.tasks import _trigger_jellyfin_refresh

    settings = MagicMock()
    settings.jellyfin_url = None
    settings.jellyfin_api_key = None

    async def mock_fetch_settings():
        return settings

    log_path = str(tmp_path / "test.log")
    mock_redis = AsyncMock()

    with patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", AsyncMock()) as mock_update:
        await _trigger_jellyfin_refresh("job-id", log_path, mock_redis)

    mock_update.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.no_jellyfin_stub
async def test_trigger_jellyfin_refresh_stamps_job_on_success(tmp_path):
    """Configured + scan succeeds → job updated with jellyfin_refreshed_at + event published."""
    from app.worker.tasks import _trigger_jellyfin_refresh

    settings = MagicMock()
    settings.jellyfin_url = "http://jf.local"
    settings.jellyfin_api_key = "secret"

    async def mock_fetch_settings():
        return settings

    async def mock_safe(_settings):
        return True

    job = _make_job()

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        return job

    log_path = str(tmp_path / "test.log")
    mock_redis = AsyncMock()

    with patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.services.jellyfin.trigger_library_scan_safe", mock_safe), \
         patch("app.worker.tasks._update_job", mock_update):
        await _trigger_jellyfin_refresh("job-id", log_path, mock_redis)

    assert job.jellyfin_refreshed_at is not None
    mock_redis.publish.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.no_jellyfin_stub
async def test_trigger_jellyfin_refresh_does_not_stamp_on_failure(tmp_path):
    """Configured but scan fails → no DB write, log records WARN."""
    from app.worker.tasks import _trigger_jellyfin_refresh

    settings = MagicMock()
    settings.jellyfin_url = "http://jf.local"
    settings.jellyfin_api_key = "secret"

    async def mock_fetch_settings():
        return settings

    async def mock_safe(_settings):
        return False

    log_path = str(tmp_path / "test.log")
    mock_redis = AsyncMock()

    with patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.services.jellyfin.trigger_library_scan_safe", mock_safe), \
         patch("app.worker.tasks._update_job", AsyncMock()) as mock_update:
        await _trigger_jellyfin_refresh("job-id", log_path, mock_redis)

    mock_update.assert_not_called()
    assert "Jellyfin library refresh failed" in (tmp_path / "test.log").read_text()


# ---------------------------------------------------------------------------
# _compress_audio_for_remote
# ---------------------------------------------------------------------------

def test_compress_audio_for_remote_builds_16k_mono_mp3(monkeypatch):
    """WAV → 16 kHz mono 32 kbps MP3; returns the .mp3 path next to the WAV."""
    calls = {}
    class FakeStream:
        def output(self, path, **kw):
            calls["out_path"] = path
            calls["out_kw"] = kw
            return self
        def overwrite_output(self):
            return self
        def run(self, **kw):
            calls["run_kw"] = kw
            return (b"", b"")
    fake_ffmpeg = MagicMock()
    fake_ffmpeg.input.return_value = FakeStream()
    with patch.dict("sys.modules", {"ffmpeg": fake_ffmpeg}):
        out = _compress_audio_for_remote("/tmp/job-1.wav")
    assert out == "/tmp/job-1.remote.mp3"
    fake_ffmpeg.input.assert_called_once_with("/tmp/job-1.wav")
    assert calls["out_path"] == "/tmp/job-1.remote.mp3"
    assert calls["out_kw"] == {
        "acodec": "libmp3lame", "ac": 1, "ar": "16000", "audio_bitrate": "32k"
    }


def test_guard_remote_audio_size_raises_above_cap(tmp_path):
    """A compressed file over the cap fails fast with an actionable message."""
    big = tmp_path / "big.remote.mp3"
    big.write_bytes(b"x")
    import app.worker.tasks as t
    with patch.object(t.os.path, "getsize", return_value=t._REMOTE_TRANSCRIPTION_MAX_BYTES + 1):
        with pytest.raises(RuntimeError, match=r"Audio too large for hosted transcription"):
            t._guard_remote_audio_size(str(big))


def test_guard_remote_audio_size_ok_under_cap(tmp_path):
    f = tmp_path / "ok.remote.mp3"
    f.write_bytes(b"x")
    import app.worker.tasks as t
    with patch.object(t.os.path, "getsize", return_value=1024):
        t._guard_remote_audio_size(str(f))  # no exception


def test_remote_blocking_compresses_and_uploads_mp3(monkeypatch, tmp_path):
    """Remote path compresses the WAV, size-guards, uploads the MP3
    (not the WAV), and removes the temp MP3 afterward."""
    import app.worker.tasks as t
    mp3 = str(tmp_path / "j.remote.mp3"); open(mp3, "wb").write(b"AUDIO")
    monkeypatch.setattr(t, "_compress_audio_for_remote", lambda w: mp3)
    monkeypatch.setattr(t, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(t, "_wait_remote_ready", lambda url, **k: None)  # skip warm-up (added by RES-T2)

    captured = {}
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"language": "en", "segments": [
            {"start": 0.0, "end": 1.0, "text": "hi"}]}
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, files=None, data=None):
            captured["fname"] = files["file"][0]
            captured["mime"] = files["file"][2]
            return Resp()
    monkeypatch.setattr(t.httpx, "Client", Client)

    out = t._run_transcription_remote_blocking(str(tmp_path / "j.wav"),
              "https://api.groq.com/openai/v1", "whisper-large-v3-turbo", "gk")
    assert out == {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}], "words": []}
    assert captured["fname"] == "j.remote.mp3"
    assert captured["mime"] == "audio/mpeg"
    assert not os.path.exists(mp3)  # temp mp3 cleaned up


def test_remote_blocking_surfaces_upstream_http_error(monkeypatch, tmp_path):
    """An upstream 413/4xx is re-raised with status + provider message."""
    import app.worker.tasks as t
    mp3 = str(tmp_path / "j.remote.mp3"); open(mp3, "wb").write(b"A")
    monkeypatch.setattr(t, "_compress_audio_for_remote", lambda w: mp3)
    monkeypatch.setattr(t, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(t, "_wait_remote_ready", lambda url, **k: None)  # skip warm-up (added by RES-T2)
    req = t.httpx.Request("POST", "https://api.groq.com/openai/v1/audio/transcriptions")
    resp = t.httpx.Response(413, json={"error": {"message": "file too large"}}, request=req)
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return resp
    monkeypatch.setattr(t.httpx, "Client", Client)
    with pytest.raises(RuntimeError, match=r"413.*file too large"):
        t._run_transcription_remote_blocking(str(tmp_path / "j.wav"),
            "https://api.groq.com/openai/v1", "m", "k")
    assert not os.path.exists(mp3)



def test_compress_audio_for_remote_removes_partial_on_ffmpeg_failure(monkeypatch, tmp_path):
    """If ffmpeg dies mid-write, the partial .remote.mp3 must not leak."""
    import app.worker.tasks as t
    wav = str(tmp_path / "j.wav")
    partial = str(tmp_path / "j.remote.mp3")
    open(partial, "wb").write(b"PARTIAL")  # simulate a partial ffmpeg write

    class Boom(Exception):
        pass

    class FakeStream:
        def output(self, *a, **k):
            return self
        def overwrite_output(self):
            return self
        def run(self, **k):
            raise Boom("ffmpeg exploded")

    fake_ffmpeg = MagicMock()
    fake_ffmpeg.input.return_value = FakeStream()
    with patch.dict("sys.modules", {"ffmpeg": fake_ffmpeg}):
        with pytest.raises(Boom):
            t._compress_audio_for_remote(wav)
    assert not os.path.exists(partial)  # partial cleaned up, exception re-raised


# ---------------------------------------------------------------------------
# SP-2: _job_backend — per-job config snapshot accessor
# ---------------------------------------------------------------------------

def test_job_backend_returns_snapshot_or_raises():
    import app.worker.tasks as t
    j = MagicMock(); j.backend_profile = {"transcription_backend": "remote-api"}
    assert t._job_backend(j)["transcription_backend"] == "remote-api"
    j2 = MagicMock(); j2.backend_profile = None
    with pytest.raises(RuntimeError, match="no backend profile"):
        t._job_backend(j2)


# ---------------------------------------------------------------------------
# SP2-T7: dual-SRT output — source SRT always, target SRT when translating
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_writes_source_then_target_srt_when_translating(tmp_path):
    """Translating job → source SRT (src lang) then target SRT (tgt lang), in order."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="en",
        target_language="pl",
        translation_provider="ollama",
        translation_model="llama3",
        backend_profile={
            "translation_provider": "ollama",
            "translation_model": "llama3",
            "translation_api_url": "http://ollama:11434",
            "translation_api_key": None,
        },
    )
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()
    src_segments = [{"start": 0.0, "end": 1.0, "text": "Hello"}]
    tgt_segments = [{"start": 0.0, "end": 1.0, "text": "Cześć"}]

    write_calls = []

    async def mock_write_srt_for(job, job_id, segments, lang, log_path, redis_client):
        write_calls.append((lang, f"/media/Film.{lang}.srt"))
        return f"/media/Film.{lang}.srt"

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=src_segments)), \
         patch("app.worker.tasks._translate", AsyncMock(return_value=tgt_segments)), \
         patch("app.worker.tasks._write_srt_for", mock_write_srt_for), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    # Two SRT writes: source first, then target
    assert len(write_calls) == 2
    assert write_calls[0][0] == "en"   # source language first
    assert write_calls[1][0] == "pl"   # target language second
    # Returned srt_path is the target SRT
    assert result["srt_path"] == "/media/Film.pl.srt"


@pytest.mark.asyncio
async def test_pipeline_writes_only_source_srt_when_not_translating(tmp_path):
    """No translation (target_language None) → exactly one _write_srt_for call,
    at the source language; returned srt_path is the source one."""
    job = _make_job(
        file_path="/media/Film.mkv",
        source_language="fr",
        target_language=None,
    )
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()
    src_segments = [{"start": 0.0, "end": 1.0, "text": "Bonjour"}]

    write_calls = []

    async def mock_write_srt_for(job, job_id, segments, lang, log_path, redis_client):
        write_calls.append((lang, f"/media/Film.{lang}.srt"))
        return f"/media/Film.{lang}.srt"

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=src_segments)), \
         patch("app.worker.tasks._write_srt_for", mock_write_srt_for), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    # Exactly one SRT write: source only
    assert len(write_calls) == 1
    assert write_calls[0][0] == "fr"   # source language
    # Returned srt_path is the source SRT
    assert result["srt_path"] == "/media/Film.fr.srt"


# ---------------------------------------------------------------------------
# SP-3 Task 2: _post_translation_with_retries returns (content, response)
# ---------------------------------------------------------------------------

def test_post_translation_returns_content_and_response(monkeypatch):
    import app.worker.tasks as t

    class Resp:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": " hi "}}],
                    "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6, "cost": 0.0001}}

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return Resp()

    monkeypatch.setattr(t.httpx, "Client", Client)
    content, data = t._post_translation_with_retries("http://x/v1/chat/completions", {}, {"model": "m"})
    assert content == "hi"
    assert data["usage"]["total_tokens"] == 6
    assert data["usage"]["cost"] == 0.0001


# ---------------------------------------------------------------------------
# SP-3 Task 3: _run_translation accumulates usage across glossary + segments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_translation_accumulates_and_persists_usage(tmp_path, monkeypatch):
    """Real SP-2 job state (translation_provider ORM col=None, config in
    backend_profile). Sums usage across glossary + N segment calls and
    persists ONE _update_job with the four metrics + provider/model from
    the snapshot."""
    import app.worker.tasks as t
    from app.worker.usage import Usage

    job = _make_job(
        file_path="/m/x.mkv", source_language="en", target_language="pl",
        translation_provider=None, translation_model=None,
        backend_profile={
            "translation_provider": "openrouter",
            "translation_model": "google/gemini-2.0-flash-001",
            "translation_api_url": None, "translation_api_key": "or-k",
        },
    )
    updates = []
    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updates.append(dict(fields)); return job
    monkeypatch.setattr(t, "_update_job", mock_update)
    # WS5: the batch loop polls job status per batch for cancellation
    monkeypatch.setattr(t, "_fetch_job", AsyncMock(return_value=job))
    monkeypatch.setattr(t, "_publish_event", AsyncMock())
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)

    async def fake_bible(loop, segments, mapped_model, base_url, api_key, log_path, job_id, target_language):
        return ({"names": ["Spider"]},
                [{"usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6, "cost": 0.001}}])
    monkeypatch.setattr(t, "_extract_film_bible", fake_bible)

    async def fake_batch(loop, chunk, tgt=None, *, acc, **kw):
        for segment in chunk:
            segment["text"] = "T:" + segment["text"]
            acc.add(Usage(3, 2, 5, 0.002))
    monkeypatch.setattr(t, "_translate_batch", fake_batch)

    segs = [{"text": "a"}, {"text": "b"}]
    await t._run_translation(job, "jid", segs, str(tmp_path / "l.log"), AsyncMock())

    final = [u for u in updates if "total_tokens" in u]
    assert len(final) == 1
    f = final[0]
    assert f["prompt_tokens"] == 5 + 3 * 2
    assert f["completion_tokens"] == 1 + 2 * 2
    assert f["total_tokens"] == 6 + 5 * 2
    assert abs(f["cost_usd"] - (0.001 + 0.002 * 2)) < 1e-9
    assert f["translation_provider"] == "openrouter"
    assert f["translation_model"] == "google/gemini-2.0-flash-001"


# ---------------------------------------------------------------------------
# Task 2: _parse_batch_response
# ---------------------------------------------------------------------------

def test_parse_batch_aligned():
    raw = "1. Cześć.\n2. Jak się masz?\n3. Dobrze."
    assert _parse_batch_response(raw, 3) == ["Cześć.", "Jak się masz?", "Dobrze."]


def test_parse_batch_tolerates_fences_and_prose():
    raw = "```\nSure:\n1. A\n2. B\n```"
    assert _parse_batch_response(raw, 2) == ["A", "B"]


def test_parse_batch_wrong_count_returns_none():
    assert _parse_batch_response("1. A\n2. B", 3) is None


def test_parse_batch_missing_number_returns_none():
    assert _parse_batch_response("1. A\n3. C", 3) is None


def test_parse_batch_blank_translation_returns_none():
    assert _parse_batch_response("1. A\n2.   \n3. C", 3) is None


# ---------------------------------------------------------------------------
# Task 3: _translate_batch
# ---------------------------------------------------------------------------

import asyncio
from app.worker import tasks


async def test_translate_batch_assigns_on_aligned(monkeypatch):
    chunk = [{"text": "Hello."}, {"text": "Bye."}]
    monkeypatch.setattr(tasks, "_translate_batch_blocking",
                        lambda *a, **k: (["Cześć.", "Pa."], "1. Cześć.\n2. Pa.", {"usage": {}}))
    acc = tasks.UsageAccumulator()
    tgt = tasks._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                                 base_url=None, api_key=None, target_language="pl")
    await tasks._translate_batch(
        asyncio.get_running_loop(), chunk, tgt, context_pairs=[], acc=acc,
    )
    assert [c["text"] for c in chunk] == ["Cześć.", "Pa."]


async def test_translate_batch_falls_back_per_cue_on_misalignment(monkeypatch):
    chunk = [{"text": "Hello."}, {"text": "Bye."}]
    monkeypatch.setattr(tasks, "_translate_batch_blocking", lambda *a, **k: (None, "junk", {}))
    called = []

    async def fake_one(loop, segment, tgt=None, **kw):
        called.append(segment["text"])
        segment["text"] = "X"
    monkeypatch.setattr(tasks, "_translate_one_segment", fake_one)
    acc = tasks.UsageAccumulator()
    tgt = tasks._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                                 base_url=None, api_key=None, target_language="pl")
    await tasks._translate_batch(
        asyncio.get_running_loop(), chunk, tgt, context_pairs=[], acc=acc,
    )
    assert called == ["Hello.", "Bye."]
    assert [c["text"] for c in chunk] == ["X", "X"]


# ---------------------------------------------------------------------------
# Translation temperature pinning
# ---------------------------------------------------------------------------

def test_glossary_request_pins_low_temperature():
    mock_client = _glossary_mock_client('[]')
    with patch("httpx.Client", return_value=mock_client):
        _extract_glossary_blocking("some source text", "ollama/x", "http://x", None)
    body = mock_client.post.call_args.kwargs["json"]
    assert body["temperature"] == 0.2


def test_segment_translation_request_pins_low_temperature():
    mock_client = _glossary_mock_client("Bonjour")
    with patch("httpx.Client", return_value=mock_client):
        _translate_segment_blocking("Hello", "ollama/x", "http://x", None, "fr")
    body = mock_client.post.call_args.kwargs["json"]
    assert body["temperature"] == 0.2


def test_batch_translation_request_pins_low_temperature():
    mock_client = _glossary_mock_client("1. Bonjour")
    with patch("httpx.Client", return_value=mock_client):
        _translate_batch_blocking(["Hello"], "ollama/x", "http://x", None, "fr")
    body = mock_client.post.call_args.kwargs["json"]
    assert body["temperature"] == 0.2


# ---------------------------------------------------------------------------
# WS2 (2026-07 audit): ASR quality filters, language hint, suffix normalization
# ---------------------------------------------------------------------------

def test_remote_blocking_sends_language_hint_and_keeps_confidence(monkeypatch, tmp_path):
    """The user's source-language hint is sent to the transcriber and the
    confidence fields survive the segment reduction."""
    import app.worker.tasks as t
    mp3 = str(tmp_path / "j.remote.mp3"); open(mp3, "wb").write(b"AUDIO")
    monkeypatch.setattr(t, "_compress_audio_for_remote", lambda w: mp3)
    monkeypatch.setattr(t, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(t, "_wait_remote_ready", lambda url, **k: None)

    captured = {}
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"language": "pl", "segments": [
            {"start": 0.0, "end": 1.0, "text": "hej",
             "no_speech_prob": 0.9, "avg_logprob": -0.2, "compression_ratio": 1.1}]}
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, files=None, data=None):
            captured["data"] = data
            return Resp()
    monkeypatch.setattr(t.httpx, "Client", Client)

    out = t._run_transcription_remote_blocking(
        str(tmp_path / "j.wav"), "https://x/v1", "large-v3", None, language_hint="pl")
    assert captured["data"]["language"] == "pl"
    seg = out["segments"][0]
    assert seg["no_speech_prob"] == 0.9
    assert seg["avg_logprob"] == -0.2
    assert seg["compression_ratio"] == 1.1


def test_remote_blocking_omits_language_without_hint(monkeypatch, tmp_path):
    import app.worker.tasks as t
    mp3 = str(tmp_path / "j.remote.mp3"); open(mp3, "wb").write(b"AUDIO")
    monkeypatch.setattr(t, "_compress_audio_for_remote", lambda w: mp3)
    monkeypatch.setattr(t, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(t, "_wait_remote_ready", lambda url, **k: None)
    captured = {}
    class Resp:
        def raise_for_status(self): pass
        def json(self): return {"language": "en", "segments": [{"start": 0, "end": 1, "text": "hi"}]}
    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, files=None, data=None):
            captured["data"] = data
            return Resp()
    monkeypatch.setattr(t.httpx, "Client", Client)
    t._run_transcription_remote_blocking(str(tmp_path / "j.wav"), "https://x/v1", "m", None)
    assert "language" not in captured["data"]


def test_postprocess_no_speech_raises():
    import app.worker.tasks as t
    with pytest.raises(RuntimeError, match="No speech detected"):
        t._postprocess_transcription({"language": "en", "segments": [], "words": []}, None)


def test_postprocess_all_segments_filtered_raises():
    import app.worker.tasks as t
    result = {"language": "en", "words": [],
              "segments": [{"start": 0.0, "end": 2.0, "text": "Thanks for watching!"}]}
    with pytest.raises(RuntimeError, match="No speech detected"):
        t._postprocess_transcription(result, None)


def test_postprocess_prefers_user_hint_and_normalizes():
    import app.worker.tasks as t
    result = {"language": "english", "words": [],
              "segments": [{"start": 0.0, "end": 2.0, "text": "Real line."}]}
    _, _, lang = t._postprocess_transcription(dict(result), "pl")
    assert lang == "pl"
    _, _, lang = t._postprocess_transcription(dict(result), None)
    assert lang == "en"


def test_postprocess_filters_words_inside_dropped_ranges():
    import app.worker.tasks as t
    segments = ([{"start": float(i), "end": i + 0.9, "text": "Loop line here."} for i in range(6)]
                + [{"start": 10.0, "end": 11.0, "text": "Real."}])
    words = ([{"text": "Loop", "start": float(i), "end": i + 0.4} for i in range(6)]
             + [{"text": "Real.", "start": 10.0, "end": 10.5}])
    result = {"language": "en", "segments": segments, "words": words}
    out, dropped, _ = t._postprocess_transcription(result, None)
    assert len(out["segments"]) == 3  # 2 of the loop + Real.
    kept_words = [w["text"] for w in out["words"]]
    assert "Real." in kept_words
    assert len(kept_words) == 3  # words in dropped ranges removed
    assert all(d["reason"] == "repeat_loop" for d in dropped)


@pytest.mark.asyncio
async def test_pipeline_normalizes_language_suffix(tmp_path):
    """A provider-style full language name ('english') must yield Movie.en.srt."""
    nas = tmp_path
    video = nas / "Film.mkv"
    video.touch()
    job = _make_job(file_path=str(video), source_language="english", target_language=None)
    settings = MagicMock()
    settings.nas_mount_path = str(nas)

    async def mock_fetch(job_id): return job
    async def mock_fetch_settings(): return settings
    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    transcription = {"language": "english", "segments": [
        {"start": 0.0, "end": 3.0, "text": "One line here."}], "words": []}
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=transcription)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    assert (nas / "Film.en.srt").exists()
    assert not (nas / "Film.english.srt").exists()


# ---------------------------------------------------------------------------
# WS3 (2026-07 audit): transport hardening + output validation
# ---------------------------------------------------------------------------

def _chat_resp_client(monkeypatch, contents, statuses=None, finish_reasons=None):
    """Client mock returning a sequence of chat replies; records bodies."""
    import app.worker.tasks as t
    state = {"calls": 0, "bodies": []}
    contents = list(contents)
    statuses = list(statuses or [200] * len(contents))
    finish_reasons = list(finish_reasons or ["stop"] * len(contents))

    class Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers=None, json=None):
            i = min(state["calls"], len(contents) - 1)
            state["calls"] += 1
            state["bodies"].append(json)
            status = statuses[i]
            req = t.httpx.Request("POST", url)
            if status != 200:
                return t.httpx.Response(status, request=req, json={})
            return t.httpx.Response(200, request=req, json={
                "choices": [{"message": {"content": contents[i]},
                             "finish_reason": finish_reasons[i]}]})
    monkeypatch.setattr(t.httpx, "Client", Client)
    return state


def test_post_translation_strips_think_tags(monkeypatch):
    import app.worker.tasks as t
    _chat_resp_client(monkeypatch, ["<think>Let me reason. 1. no</think>\n1. Cześć"])
    content, _ = t._post_translation_with_retries("http://x", {}, {})
    assert content == "1. Cześć"


def test_post_translation_drops_unclosed_think(monkeypatch):
    import app.worker.tasks as t
    _chat_resp_client(monkeypatch, ["<think>rambling forever"])
    with pytest.raises(Exception):
        t._post_translation_with_retries("http://x", {}, {})


def test_post_translation_fails_fast_on_401(monkeypatch):
    import app.worker.tasks as t
    state = _chat_resp_client(monkeypatch, ["never"], statuses=[401])
    with pytest.raises(Exception):
        t._post_translation_with_retries("http://x", {}, {})
    assert state["calls"] == 1  # terminal 4xx must not be hammered 3x


def test_post_translation_retries_transient_with_backoff(monkeypatch):
    import app.worker.tasks as t
    sleeps = []
    monkeypatch.setattr(t.time, "sleep", lambda s: sleeps.append(s))
    state = _chat_resp_client(monkeypatch, ["x", "x", "1. OK"], statuses=[503, 503, 200])
    content, _ = t._post_translation_with_retries("http://x", {}, {})
    assert content == "1. OK"
    assert state["calls"] == 3
    assert len(sleeps) == 2 and all(s > 0 for s in sleeps)


def test_batch_blocking_sets_max_tokens_and_returns_raw(monkeypatch):
    import app.worker.tasks as t
    state = _chat_resp_client(monkeypatch, ["1. Bonjour"])
    parsed, raw, data = t._translate_batch_blocking(["Hello"], "ollama/x", "http://x", None, "fr")
    assert parsed == ["Bonjour"]
    assert raw == "1. Bonjour"
    assert state["bodies"][0]["max_tokens"] >= 128


def test_batch_blocking_truncated_reply_is_misaligned(monkeypatch):
    import app.worker.tasks as t
    _chat_resp_client(monkeypatch, ["1. Bonjour"], finish_reasons=["length"])
    parsed, raw, data = t._translate_batch_blocking(["Hello"], "ollama/x", "http://x", None, "fr")
    assert parsed is None


def test_parse_batch_response_duplicate_numbers_is_failure():
    from app.worker.tasks import _parse_batch_response
    assert _parse_batch_response("1. a\n1. b\n2. c", 2) is None


async def test_translate_batch_corrective_reask_recovers(monkeypatch):
    import app.worker.tasks as t
    chunk = [{"text": "Hello."}, {"text": "Bye."}]
    calls = []

    def fake_blocking(texts, mapped_model, base_url, api_key, target_language,
                      context_pairs=None, glossary=None, source_language=None,
                      prior_reply=None, bible=None, story_so_far=None):
        calls.append(prior_reply)
        if prior_reply is None:
            return None, "1. Cześć. 2. Pa.", {}   # single-line mess
        return ["Cześć.", "Pa."], "1. Cześć.\n2. Pa.", {}
    monkeypatch.setattr(t, "_translate_batch_blocking", fake_blocking)
    per_cue = []

    async def fake_one(loop, segment, **kw):
        per_cue.append(segment["text"])
    monkeypatch.setattr(t, "_translate_one_segment", fake_one)
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                       base_url=None, api_key=None, target_language="pl")
    await t._translate_batch(
        asyncio.get_running_loop(), chunk, tgt, context_pairs=[], acc=acc,
    )
    assert [c["text"] for c in chunk] == ["Cześć.", "Pa."]
    assert calls == [None, "1. Cześć. 2. Pa."]  # exactly one corrective re-ask
    assert per_cue == []                         # no per-cue fallback needed


def test_clean_single_translation_rules():
    from app.worker.tasks import _clean_single_translation
    assert _clean_single_translation("Hello.", '"Cześć."') == "Cześć."
    assert _clean_single_translation("Hello.", "I'm sorry, I cannot translate that.") is None
    assert _clean_single_translation("Hello.", "Here is the translation: Cześć.") is None
    assert _clean_single_translation("Hello.", "") is None
    assert _clean_single_translation("Hi", "x" * 500) is None
    assert _clean_single_translation("Hello.", "Cześć.") == "Cześć."


async def test_translate_one_segment_retries_refusal_then_keeps_source(monkeypatch):
    import app.worker.tasks as t
    replies = ["I'm sorry, I can't help with that.", "I'm sorry, no."]

    def fake_seg_blocking(text, mapped_model, base_url, api_key, target_language,
                          context_pairs=None, glossary=None, source_language=None,
                          prior_reply=None, bible=None):
        return replies.pop(0), {}
    monkeypatch.setattr(t, "_translate_segment_blocking", fake_seg_blocking)
    seg = {"text": "Shoot him!"}
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                       base_url=None, api_key=None, target_language="pl")
    await t._translate_one_segment(asyncio.get_running_loop(), seg, tgt, acc=acc)
    assert seg["text"] == "Shoot him!"  # source kept, refusal never shipped
    assert replies == []                # exactly two attempts


def test_film_bible_chunks_long_transcripts(monkeypatch):
    import app.worker.tasks as t
    state = _chat_resp_client(monkeypatch, ['{"names": ["Jake"], "characters": [], "terms": {}, "setting": "", "register": ""}'])
    long_text = ("Some dialogue line here.\n" * 800)  # ~20k chars
    segs = [{"text": ln} for ln in long_text.splitlines()]

    async def run():
        return await t._extract_film_bible(
            asyncio.get_running_loop(), segs, "ollama/x", "http://x", None,
            "/tmp/x.log", "jid", "pl")
    import asyncio as aio
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)
    bible, datas = aio.run(run())
    assert bible["names"] == ["Jake"]
    assert state["calls"] >= 3          # chunked, not one giant prompt
    assert isinstance(datas, list) and len(datas) == state["calls"]


# ---------------------------------------------------------------------------
# WS5 (2026-07 audit): pipeline entry guard + CAS completion + cancel-in-loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_noops_on_redelivered_completed_job(tmp_path):
    """A redelivered Celery message for a completed job must NOT re-run the
    pipeline (acks_late + 24h visibility timeout redeliveries are real)."""
    job = _make_job(file_path="/media/Film.mkv", source_language="en", target_language=None)
    job.status = JobStatus.completed
    extract = AsyncMock()
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._extract_audio", extract), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")
    assert result["status"] == JobStatus.completed
    extract.assert_not_called()


@pytest.mark.asyncio
async def test_pipeline_noops_on_processing_job(tmp_path):
    """status=processing means another worker owns the job — orphan recovery
    (which flips it to queued first) is the only sanctioned re-entry."""
    job = _make_job(file_path="/media/Film.mkv", source_language="en", target_language=None)
    job.status = JobStatus.processing
    extract = AsyncMock()
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._extract_audio", extract), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")
    assert result["status"] == JobStatus.processing
    extract.assert_not_called()


@pytest.mark.asyncio
async def test_completion_is_compare_and_set(tmp_path):
    """A cancel that lands between the last phase and the terminal write must
    win — completed is only written over status=processing."""
    import app.worker.tasks as t
    calls = {}

    async def fake_complete(job_id, **fields):
        calls["fields"] = fields
        return None  # 0 rows updated -> job was cancelled mid-flight

    nas = tmp_path
    video = nas / "Film.mkv"; video.touch()
    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock(); settings.nas_mount_path = str(nas)

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    transcription = {"language": "en", "segments": [
        {"start": 0.0, "end": 3.0, "text": "One line."}], "words": []}
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._complete_job_if_processing", fake_complete), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=transcription)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")
    assert result["status"] == JobStatus.cancelled
    assert calls["fields"]["status"] == JobStatus.completed  # attempted CAS


@pytest.mark.asyncio
async def test_translation_loop_stops_on_cancel(monkeypatch, tmp_path):
    """Cancelling mid-translation stops the batch loop within one batch —
    no more paying the LLM for a cancelled job's remaining 80 batches."""
    import app.worker.tasks as t
    job = _make_job(file_path="/m/F.mkv", source_language="en", target_language="pl")
    job.backend_profile = {"translation_provider": "ollama", "translation_model": "m",
                           "translation_api_url": "http://x", "translation_api_key": None}
    segments = [{"start": float(i), "end": i + 1.0, "text": f"Line {i}."} for i in range(40)]
    batches = {"n": 0}

    async def fake_batch(loop, chunk, tgt=None, **kw):
        batches["n"] += 1
        for seg in chunk: seg["text"] = "T:" + seg["text"]
    cancelled_after = 1
    status_reads = {"n": 0}

    async def fake_fetch(job_id):
        status_reads["n"] += 1
        if batches["n"] >= cancelled_after:
            job.status = JobStatus.cancelled
        return job

    async def fake_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    monkeypatch.setattr(t, "_translate_batch", fake_batch)
    monkeypatch.setattr(t, "_fetch_job", fake_fetch)
    monkeypatch.setattr(t, "_update_job", fake_update)
    monkeypatch.setattr(t, "_publish_event", AsyncMock())
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)

    async def fake_bible(loop, segs, mm, bu, ak, lp, jid, tl):
        return {}, []
    monkeypatch.setattr(t, "_extract_film_bible", fake_bible)

    with pytest.raises(t._JobCancelled):
        await t._run_translation(job, "jid", segments, str(tmp_path / "l.log"), AsyncMock())
    assert batches["n"] <= 2  # stopped within one batch of the cancel


# ---------------------------------------------------------------------------
# WS6 (2026-07 audit): VAD pre-filter wiring
# ---------------------------------------------------------------------------

def test_postprocess_uses_speech_regions():
    import app.worker.tasks as t
    result = {"language": "en", "words": [], "segments": [
        {"start": 1.0, "end": 3.0, "text": "Real line."},
        {"start": 100.0, "end": 102.0, "text": "Thanks for hallucinating!"}]}
    out, dropped, _ = t._postprocess_transcription(result, None, speech_regions=[(0.5, 3.5)])
    assert [s["text"] for s in out["segments"]] == ["Real line."]
    assert dropped[0]["reason"] == "no_speech_region"


@pytest.mark.asyncio
async def test_pipeline_runs_vad_and_filters_silence_segments(tmp_path):
    nas = tmp_path
    video = nas / "Film.mkv"; video.touch()
    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock(); settings.nas_mount_path = str(nas)

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    transcription = {"language": "en", "words": [], "segments": [
        {"start": 0.5, "end": 3.0, "text": "Spoken line here."},
        {"start": 200.0, "end": 202.0, "text": "Silence hallucination."}]}
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks.detect_speech_regions", return_value=[(0.0, 4.0)]), \
         patch("app.worker.tasks._run_transcription_remote_blocking",
               return_value=transcription), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    srt = (nas / "Film.en.srt").read_text()
    assert "Spoken line here." in srt
    assert "Silence hallucination." not in srt
    # regions persisted for the sync self-check
    assert (tmp_path / "test-job-id.vad.json").exists()


# ---------------------------------------------------------------------------
# WS7 (2026-07 audit): explicit audio-stream selection at extraction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_audio_maps_language_matched_stream(tmp_path):
    """ffmpeg must be told WHICH audio stream to use — its default picks the
    most-channels stream (5.1 dub/commentary) over the stereo original."""
    job = _make_job(file_path="/media/Film.mkv", source_language="en")
    settings = MagicMock(); settings.nas_mount_path = "/media"

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    fake_ffmpeg = MagicMock()
    fake_ffmpeg.probe.return_value = {"streams": [
        {"index": 0, "codec_type": "video"},
        {"index": 1, "codec_type": "audio", "channels": 6,
         "tags": {"language": "fre"}, "disposition": {"default": 1}},
        {"index": 2, "codec_type": "audio", "channels": 2,
         "tags": {"language": "eng"}, "disposition": {"default": 0}},
    ]}
    selected = {}
    inp = MagicMock()
    inp.__getitem__ = MagicMock(side_effect=lambda spec: selected.setdefault("spec", spec) or MagicMock())
    fake_ffmpeg.input.return_value = inp

    from app.worker.tasks import _extract_audio
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._publish_event", AsyncMock()), \
         patch.dict("sys.modules", {"ffmpeg": fake_ffmpeg}):
        await _extract_audio(job, "jid", str(tmp_path / "a.wav"), str(tmp_path / "l.log"), AsyncMock())

    assert selected["spec"] == "a:1"  # the English stereo track, not the French 5.1


# ---------------------------------------------------------------------------
# WS8 (2026-07 audit): scene batching + film bible + story summary
# ---------------------------------------------------------------------------

def test_batch_cues_by_scene_splits_on_gaps():
    import app.worker.tasks as t
    segs = ([{"start": float(i), "end": i + 0.9, "text": f"A{i}"} for i in range(8)]
            + [{"start": 60.0 + i, "end": 60.9 + i, "text": f"B{i}"} for i in range(6)])
    batches = t.batch_cues_by_scene(segs)
    assert len(batches) == 2
    assert [s["text"] for s in batches[0]] == [f"A{i}" for i in range(8)]


def test_batch_cues_by_scene_caps_batch_size():
    import app.worker.tasks as t
    segs = [{"start": float(i), "end": i + 0.9, "text": f"L{i}"} for i in range(40)]
    batches = t.batch_cues_by_scene(segs)
    assert all(len(b) <= t.SCENE_BATCH_MAX_CUES for b in batches)
    assert sum(len(b) for b in batches) == 40


def test_batch_cues_by_scene_avoids_tiny_batches_on_gaps():
    import app.worker.tasks as t
    # a gap after only 2 cues should NOT start a new batch (min size)
    segs = ([{"start": 0.0, "end": 0.9, "text": "A"},
             {"start": 1.0, "end": 1.9, "text": "B"}]
            + [{"start": 30.0 + i, "end": 30.9 + i, "text": f"C{i}"} for i in range(4)])
    batches = t.batch_cues_by_scene(segs)
    assert len(batches) == 1


def test_parse_bible_response_tolerates_fences_and_junk():
    import app.worker.tasks as t
    raw = 'Sure! ```json\n{"names": ["Jake"], "characters": [{"name": "Jake", "gender": "male"}], "terms": {"the Colonel": "Pułkownik"}, "setting": "War.", "register": "informal"}\n``` hope that helps'
    bible = t._parse_bible_response(raw)
    assert bible["names"] == ["Jake"]
    assert bible["characters"][0]["gender"] == "male"
    assert bible["terms"]["the Colonel"] == "Pułkownik"


def test_parse_bible_response_garbage_gives_empty():
    import app.worker.tasks as t
    assert t._parse_bible_response("I refuse.") == {}


def test_merge_bibles_first_wins_and_unions():
    import app.worker.tasks as t
    a = {"names": ["Jake"], "characters": [{"name": "Jake", "gender": "male"}],
         "terms": {"Colonel": "Pułkownik"}, "setting": "War.", "register": "informal"}
    b = {"names": ["Jake", "Neytiri"], "characters": [
            {"name": "Jake", "gender": "unknown"},
            {"name": "Neytiri", "gender": "female"}],
         "terms": {"Colonel": "different", "banshee": "ikran"}, "setting": "", "register": ""}
    m = t._merge_bibles([a, b])
    assert m["names"] == ["Jake", "Neytiri"]
    assert {c["name"]: c["gender"] for c in m["characters"]} == {
        "Jake": "male", "Neytiri": "female"}
    assert m["terms"] == {"Colonel": "Pułkownik", "banshee": "ikran"}
    assert m["setting"] == "War."


# ---------------------------------------------------------------------------
# WS9 (2026-07 audit): transcription checkpoint + heartbeat + resumable batches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_resumes_from_transcription_checkpoint(tmp_path):
    """A job-level retry must NOT re-extract/re-transcribe when the previous
    attempt already persisted the transcription."""
    import json as _json
    nas = tmp_path
    video = nas / "Film.mkv"; video.touch()
    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock(); settings.nas_mount_path = str(nas)

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    checkpoint = {"language": "en", "segments": [
        {"start": 0.0, "end": 3.0, "text": "Line from checkpoint."}], "words": []}
    (tmp_path / "test-job-id.transcription.json").write_text(_json.dumps(checkpoint))

    extract = AsyncMock(); transcribe = AsyncMock()
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", extract), \
         patch("app.worker.tasks._transcribe", transcribe), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")

    assert result["status"] == JobStatus.completed
    extract.assert_not_called()
    transcribe.assert_not_called()
    assert "Line from checkpoint." in (nas / "Film.en.srt").read_text()
    # terminal success cleans the checkpoint
    assert not (tmp_path / "test-job-id.transcription.json").exists()


@pytest.mark.asyncio
async def test_pipeline_writes_checkpoint_after_transcription(tmp_path):
    import json as _json
    nas = tmp_path
    video = nas / "Film.mkv"; video.touch()
    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock(); settings.nas_mount_path = str(nas)
    seen = {}

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    async def spying_write_srt(job_, job_id, cues, lang, log_path, redis_client):
        p = tmp_path / "test-job-id.transcription.json"
        seen["existed_during_write"] = p.exists()
        return str(nas / "Film.en.srt")

    transcription = {"language": "en", "segments": [
        {"start": 0.0, "end": 3.0, "text": "One line."}], "words": []}
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=transcription)), \
         patch("app.worker.tasks._write_srt_for", spying_write_srt), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        await _async_pipeline("test-job-id")
    assert seen["existed_during_write"] is True


@pytest.mark.asyncio
async def test_heartbeat_bumps_updated_at_during_blocking_work():
    import app.worker.tasks as t
    bumps = []

    async def fake_update(job_id, **fields):
        bumps.append(fields)
        return MagicMock()
    with patch("app.worker.tasks._update_job", fake_update):
        async with t._job_heartbeat("jid", interval=0.02):
            await asyncio.sleep(0.09)
    assert len(bumps) >= 2  # kept the row warm while "working"


@pytest.mark.asyncio
async def test_run_translation_resumes_completed_batches(monkeypatch, tmp_path):
    """A retry after a mid-translation crash re-uses already-translated
    batches instead of paying the LLM again."""
    import json as _json
    import app.worker.tasks as t
    job = _make_job(file_path="/m/F.mkv", source_language="en", target_language="pl")
    job.backend_profile = {"translation_provider": "ollama", "translation_model": "m",
                           "translation_api_url": "http://x", "translation_api_key": None}
    segments = [{"start": float(i), "end": i + 0.9, "text": f"Line {i}."} for i in range(20)]
    batches = t.batch_cues_by_scene(segments)
    first = batches[0]
    progress = {"texts": {str(i): f"T:{s['text']}" for i, s in enumerate(segments[:len(first)])}}
    (tmp_path / "jid.translation.json").write_text(_json.dumps(progress))

    called_batches = []

    async def fake_batch(loop, chunk, tgt=None, **kw):
        called_batches.append(len(chunk))
        for seg in chunk: seg["text"] = "NEW:" + seg["text"]

    async def fake_bible(loop, segs, mm, bu, ak, lp, jid, tl):
        return {}, []
    monkeypatch.setattr(t, "_translate_batch", fake_batch)
    monkeypatch.setattr(t, "_extract_film_bible", fake_bible)
    monkeypatch.setattr(t, "_fetch_job", AsyncMock(return_value=job))
    monkeypatch.setattr(t, "_update_job", AsyncMock(return_value=job))
    monkeypatch.setattr(t, "_publish_event", AsyncMock())
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)
    monkeypatch.setattr(t, "_LOG_DIR", str(tmp_path))

    await t._run_translation(job, "jid", segments, str(tmp_path / "jid.log"), AsyncMock())
    # first batch restored from the progress file, not re-translated
    assert segments[0]["text"].startswith("T:")
    assert sum(called_batches) == 20 - len(first)


# ---------------------------------------------------------------------------
# WS10 (2026-07 audit): language-ID gate wiring
# ---------------------------------------------------------------------------

async def test_translate_batch_reasks_on_source_language_echo(monkeypatch):
    import app.worker.tasks as t
    chunk = [{"text": "Hello there, how are you doing today my friend?"}]
    replies = [(["Hello there, how are you doing today my friend?"], "1. echo", {}),
               (["Cześć, jak się dzisiaj miewasz przyjacielu?"], "1. ok", {})]

    def fake_blocking(*a, **k):
        return replies.pop(0)
    monkeypatch.setattr(t, "_translate_batch_blocking", fake_blocking)
    suspects = iter([True, False])
    monkeypatch.setattr(t, "batch_language_suspect",
                        lambda texts, tgt, src, **k: next(suspects))
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                             base_url=None, api_key=None, target_language="pl",
                             source_language="en")
    await t._translate_batch(
        asyncio.get_running_loop(), chunk, tgt, context_pairs=[], acc=acc,
    )
    assert chunk[0]["text"].startswith("Cześć")
    assert replies == []  # exactly two attempts


def test_append_worker_checks_preserves_metrics(tmp_path):
    import app.worker.tasks as t
    result = {"status": "pass", "score": 100.0,
              "report": {"summary": "PASS", "checks": [
                  {"layer": "structural", "name": "non_empty", "severity": "ok", "detail": ""}],
                  "metrics": {"cue_count": 1}}}
    srt = "1\n00:00:01,000 --> 00:00:03,000\nHello.\n"
    job = _make_job(file_path="/m/F.mkv", target_language=None)
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)):
        out = t._append_worker_checks(result, srt, job)
    names = [c["name"] for c in out["report"]["checks"]]
    assert "output_language" in names
    assert "av_sync" in names
    assert out["report"]["metrics"] == {"cue_count": 1}


# ---------------------------------------------------------------------------
# WS12 (2026-07 audit): repair pass for suspect translations
# ---------------------------------------------------------------------------

async def test_failed_validation_marks_cue_for_repair(monkeypatch):
    import app.worker.tasks as t
    replies = ["I'm sorry, I can't.", "I'm sorry, no."]

    def fake_seg_blocking(*a, **k):
        return replies.pop(0), {}
    monkeypatch.setattr(t, "_translate_segment_blocking", fake_seg_blocking)
    seg = {"text": "Shoot him!"}
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                       base_url=None, api_key=None, target_language="pl")
    await t._translate_one_segment(asyncio.get_running_loop(), seg, tgt, acc=acc)
    assert seg["text"] == "Shoot him!"
    assert seg.get("needs_repair") is True


async def test_repair_pass_retranslates_flagged_cues(monkeypatch):
    import app.worker.tasks as t
    segments = [{"start": float(i), "end": i + 1.0, "text": f"Linia {i}."} for i in range(6)]
    segments[2]["needs_repair"] = True
    segments[4]["needs_repair"] = True

    calls = []

    def fake_seg_blocking(text, *a, **k):
        calls.append(text)
        return f"NAPRAWIONE {text}", {}
    monkeypatch.setattr(t, "_translate_segment_blocking", fake_seg_blocking)
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                             base_url=None, api_key=None, target_language="pl",
                             source_language="en")
    repaired = await t._repair_pass(
        asyncio.get_running_loop(), segments, tgt,
        acc=acc, log_path="/tmp/x.log", job_id="jid",
    )
    assert repaired == 2
    assert segments[2]["text"].startswith("NAPRAWIONE")
    assert segments[4]["text"].startswith("NAPRAWIONE")
    assert "needs_repair" not in segments[2]
    assert len(calls) == 2


async def test_repair_pass_caps_volume(monkeypatch):
    import app.worker.tasks as t
    segments = [{"start": float(i), "end": i + 1.0, "text": f"Line {i}.", "needs_repair": True}
                for i in range(300)]

    def fake_seg_blocking(text, *a, **k):
        return f"OK {text}", {}
    monkeypatch.setattr(t, "_translate_segment_blocking", fake_seg_blocking)
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)
    acc = t.UsageAccumulator()
    tgt = t._TranslateTarget(provider="ollama", model="m", mapped_model="m",
                             base_url=None, api_key=None, target_language="pl",
                             source_language="en")
    repaired = await t._repair_pass(
        asyncio.get_running_loop(), segments, tgt,
        acc=acc, log_path="/tmp/x.log", job_id="jid",
    )
    assert repaired == t.REPAIR_MAX_CUES


# ---------------------------------------------------------------------------
# WS14 (2026-07 audit): shot-change snapping wiring
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pipeline_snaps_cues_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBGEN_SHOT_SNAP", "1")
    nas = tmp_path
    video = nas / "Film.mkv"; video.touch()
    job = _make_job(file_path=str(video), source_language="en", target_language=None)
    settings = MagicMock(); settings.nas_mount_path = str(nas)

    async def mock_update(job_id, **fields):
        for k, v in fields.items(): setattr(job, k, v)
        return job

    transcription = {"language": "en", "segments": [
        {"start": 0.5, "end": 3.7, "text": "A line that ends near a cut."}], "words": []}
    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", AsyncMock(return_value=job)), \
         patch("app.worker.tasks._fetch_settings", AsyncMock(return_value=settings)), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._complete_job_if_processing", _cas_via(mock_update)), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=transcription)), \
         patch("app.worker.tasks.detect_shot_changes", return_value=[4.0]), \
         patch("app.worker.tasks.aioredis.from_url", return_value=AsyncMock()):
        result = await _async_pipeline("test-job-id")
    assert result["status"] == JobStatus.completed
    srt = (nas / "Film.en.srt").read_text()
    # cue end extended to two frames before the 4.0s cut (3.917)
    assert "00:00:03,9" in srt
