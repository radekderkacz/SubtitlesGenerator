import os
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.schemas import JobStatus, JobPhase
from app.worker.tasks import (
    _async_pipeline,
    _compress_audio_for_remote,
    _extract_glossary_blocking,
    _format_srt_timestamp,
    _format_translation_error,
    _guard_remote_audio_size,
    _job_backend,
    _output_srt_path,
    _resolve_litellm_target,

    _segments_to_srt,
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
    mock_ffmpeg_module.input.return_value.output.return_value.overwrite_output.return_value.run.side_effect = (
        FfmpegError("ffmpeg", b"", b"Invalid data found")
    )

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._fetch_settings", mock_fetch_settings), \
         patch("app.worker.tasks._update_job", mock_update), \
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
    # Per-segment heartbeat: with 2 segments, expect an
    # intermediate progress emit somewhere between 65 (enter) and 80 (exit).
    # Math: 65 + int(14 * 1/2) = 72 after the first segment.
    assert 72 in progress_vals
    assert mock_client.post.call_count == 2
    call_one = mock_client.post.call_args_list[0]
    call_two = mock_client.post.call_args_list[1]
    # Ollama → {api_url}/v1/chat/completions; the litellm ``ollama/`` prefix
    # is stripped before sending to the upstream endpoint.
    assert call_one.args[0] == "http://ollama:11434/v1/chat/completions"
    assert call_one.kwargs["json"]["model"] == "llama3"
    assert "Authorization" not in call_one.kwargs["headers"]

    # New layered prompt structure: system rules + user line (subtitle-aware
    # translation prompts follow-up). The system message must carry the
    # universal rules, and the user message must carry the source line.
    msgs_one = call_one.kwargs["json"]["messages"]
    assert msgs_one[0]["role"] == "system"
    assert "proper noun" in msgs_one[0]["content"].lower()
    assert msgs_one[1]["role"] == "user"
    assert "Bonjour" in msgs_one[1]["content"]
    # First call has no prior pairs, so no continuity-context block.
    assert "Previous lines" not in msgs_one[1]["content"]

    # Second call must carry the first segment's (source, translation)
    # pair as continuity context so character names + register stay
    # consistent across the film.
    msgs_two = call_two.kwargs["json"]["messages"]
    assert msgs_two[0]["role"] == "system"
    assert msgs_two[1]["role"] == "user"
    assert "Previous lines" in msgs_two[1]["content"]
    assert "Bonjour" in msgs_two[1]["content"]
    assert "Hello" in msgs_two[1]["content"]  # the prior translation
    assert "Merci" in msgs_two[1]["content"]  # the current line


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

    # httpx.Client.post always raises ConnectionError — exhausts the 3 retry
    # attempts and surfaces as a RuntimeError chained from ConnectionError.
    mock_client = MagicMock()
    mock_client.post.side_effect = ConnectionError("connection refused")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    with patch("app.worker.tasks._LOG_DIR", str(tmp_path)), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(return_value=[{"text": "Bonjour"}])), \
         patch("app.worker.tasks._write_srt_for", AsyncMock(return_value="/tmp/test.srt")), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis), \
         patch("httpx.Client", return_value=mock_client):
        with pytest.raises(RuntimeError, match=r"Translation failed \(openai / gpt-4\): RuntimeError"):
            await _async_pipeline("test-job-id")

    assert job.status == JobStatus.failed
    assert "Translation failed" in job.error_message
    assert "openai" in job.error_message
    assert "gpt-4" in job.error_message
    # The wrapper raises RuntimeError after exhausting retries; that's what
    # the caller sees and chains into the user-visible error message. The
    # original ConnectionError is preserved as the chained ``__cause__``.
    assert "RuntimeError" in job.error_message
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


def test_segments_to_srt_normalizes_multiline_text():
    """Embedded newlines in text would break SRT cue boundaries — normalize to spaces."""
    segments = [
        {"start": 0.0, "end": 1.0, "text": "Line one\nLine two\nLine three"},
    ]
    result = _segments_to_srt(segments)
    assert "Line one Line two Line three" in result
    assert "\nLine two" not in result


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
    assert out == {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}
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
    monkeypatch.setattr(t, "_publish_event", AsyncMock())
    monkeypatch.setattr(t, "_write_log", lambda *a, **k: None)

    async def fake_glossary(loop, segments, mapped_model, base_url, api_key, log_path, job_id):
        return ["Spider"], {"usage": {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6, "cost": 0.001}}
    monkeypatch.setattr(t, "_extract_and_log_glossary", fake_glossary)

    async def fake_one(loop, segment, *, acc, **kw):
        segment["text"] = "T:" + segment["text"]
        acc.add(Usage(3, 2, 5, 0.002))
    monkeypatch.setattr(t, "_translate_one_segment", fake_one)

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
