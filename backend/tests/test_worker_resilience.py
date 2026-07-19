import httpx, time, pytest
from unittest.mock import patch, MagicMock
from app.worker.errors import TransientPipelineError
import app.worker.tasks as tasks

def _resp(status, json_body=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = json_body or {}
    r.text = text
    if status >= 400:
        req = httpx.Request("POST", "http://x/")
        hresp = httpx.Response(status, request=req)
        r.raise_for_status.side_effect = httpx.HTTPStatusError(str(status), request=req, response=hresp)
    else:
        r.raise_for_status.return_value = None
    return r

@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    # neutralise audio compression/size guard + tmp cleanup
    monkeypatch.setattr(tasks, "_compress_audio_for_remote", lambda p: p)
    monkeypatch.setattr(tasks, "_guard_remote_audio_size", lambda p: None)
    monkeypatch.setattr(tasks.os, "remove", lambda p: None)
    monkeypatch.setattr("builtins.open", lambda *a, **k: MagicMock().__enter__())

def test_remote_transcription_500_then_200_succeeds_no_rerun(monkeypatch):
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return _resp(500) if calls["n"] == 1 else _resp(200, {"language": "en", "segments": []})
    client = MagicMock(); client.post.side_effect = post
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(client))
    monkeypatch.setattr(tasks, "_wait_remote_ready", lambda url, **k: None)
    out = tasks._run_transcription_remote_blocking("/a.wav", "http://w", "large-v3", None)
    assert out == {"language": "en", "segments": [], "words": []}
    assert calls["n"] == 2  # retried the POST, no pipeline rerun

def test_remote_transcription_persistent_500_raises_TPE(monkeypatch):
    client = MagicMock(); client.post.side_effect = lambda *a, **k: _resp(500)
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(client))
    monkeypatch.setattr(tasks, "_wait_remote_ready", lambda url, **k: None)
    with pytest.raises(TransientPipelineError) as ei:
        tasks._run_transcription_remote_blocking("/a.wav", "http://w", "large-v3", None)
    assert ei.value.step == "remote-transcription"

def test_remote_transcription_400_terminal_no_retry(monkeypatch):
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1; return _resp(400, text="bad")
    client = MagicMock(); client.post.side_effect = post
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(client))
    monkeypatch.setattr(tasks, "_wait_remote_ready", lambda url, **k: None)
    with pytest.raises(RuntimeError) as ei:   # preserved terminal message
        tasks._run_transcription_remote_blocking("/a.wav", "http://w", "large-v3", None)
    assert "Remote transcription failed: 400" in str(ei.value)
    assert calls["n"] == 1

def _ctx(obj):
    cm = MagicMock(); cm.__enter__.return_value = obj; cm.__exit__.return_value = False
    return cm

def test_wait_remote_ready_polls_until_loaded(monkeypatch):
    seq = [ _hresp(200, {"model_loaded": False}), _hresp(200, {"model_loaded": True}) ]
    g = MagicMock(); g.get.side_effect = seq
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(g))
    tasks._wait_remote_ready("http://w", timeout=5, interval=0)  # returns, no raise
    assert g.get.call_count == 2

def test_wait_remote_ready_skips_on_404(monkeypatch):
    g = MagicMock(); g.get.return_value = _hresp(404, {})
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(g))
    tasks._wait_remote_ready("http://w", timeout=5, interval=0)  # no raise, no gating
    assert g.get.call_count == 1

def _hresp(status, body):
    r = MagicMock(); r.status_code = status; r.json.return_value = body; return r


def test_translation_exhausted_transient_raises_TPE(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)
    req = httpx.Request("POST", "http://x/")
    err = httpx.HTTPStatusError("503", request=req, response=httpx.Response(503, request=req))
    client = MagicMock(); client.post.side_effect = err
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(client))
    with pytest.raises(TransientPipelineError) as ei:
        tasks._post_translation_with_retries("http://t", {}, {"x": 1})
    assert ei.value.step == "translation"

def test_translation_terminal_error_fails_fast(monkeypatch):
    """WS3: terminal errors (bad JSON, 4xx) are raised on the FIRST attempt —
    no pointless 3x hammer before surfacing (was: RuntimeError after 3)."""
    client = MagicMock(); client.post.side_effect = ValueError("bad json")
    monkeypatch.setattr(tasks.httpx, "Client", lambda **k: _ctx(client))
    with pytest.raises(ValueError):
        tasks._post_translation_with_retries("http://t", {}, {"x": 1})
    assert client.post.call_count == 1


import asyncio

def _aw(v):
    async def _f():
        return v
    return _f()

def test_jellyfin_refresh_retries_then_soft(monkeypatch):
    """Transient ConnectError: must retry >=2 times and never raise."""
    n = {"c": 0}

    async def scan(_s):
        n["c"] += 1
        raise httpx.ConnectError("down")  # transient, every time

    monkeypatch.setattr("app.services.jellyfin.trigger_library_scan_safe", scan, raising=False)

    # settings with jellyfin configured
    class S:
        jellyfin_url = "http://j"
        jellyfin_api_key = "k"

    monkeypatch.setattr(tasks, "_fetch_settings", lambda: _aw(S()))
    monkeypatch.setattr(tasks, "_write_log", lambda *a, **k: None)

    # must NOT raise (job already completed) even though every attempt fails
    asyncio.run(tasks._trigger_jellyfin_refresh("jid", "/l.log", MagicMock()))
    assert n["c"] >= 2  # retried at least once before giving up softly


# ---------------------------------------------------------------------------
# Task 5 — chokepoint: transient propagates as `queued` (not `failed`);
# terminal still → `failed`. Mirrors the existing _async_pipeline test
# setup in tests/test_worker_tasks.py (test_pipeline_exception_marks_job_failed):
# same patch targets + `updated` status-capture pattern.
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock
from app.models.schemas import JobStatus


def _pipeline_job():
    job = MagicMock()
    job.id = "jid"
    job.status = "queued"
    job.target_language = None
    job.source_language = None
    job.source_srt_path = None
    return job


def _run_pipeline_capturing(transcribe_exc):
    """Run _async_pipeline with _transcribe raising `transcribe_exc`,
    capturing every status passed to _update_job. Returns (statuses, raised)."""
    job = _pipeline_job()
    updated = []

    async def mock_fetch(job_id):
        return job

    async def mock_update(job_id, **fields):
        for k, v in fields.items():
            setattr(job, k, v)
        updated.append(dict(fields))
        return job

    mock_redis = AsyncMock()
    raised = None
    with patch("app.worker.tasks._LOG_DIR", "/tmp"), \
         patch("app.worker.tasks._fetch_job", mock_fetch), \
         patch("app.worker.tasks._update_job", mock_update), \
         patch("app.worker.tasks._write_log", MagicMock()), \
         patch("app.worker.tasks._publish_event", AsyncMock()), \
         patch("app.worker.tasks._extract_audio", AsyncMock()), \
         patch("app.worker.tasks._transcribe", AsyncMock(side_effect=transcribe_exc)), \
         patch("app.worker.tasks.aioredis.from_url", return_value=mock_redis):
        try:
            asyncio.run(tasks._async_pipeline("jid"))
        except BaseException as exc:  # noqa: BLE001 — re-raised by chokepoint
            raised = exc
    statuses = [u["status"] for u in updated if "status" in u]
    return statuses, raised


def test_chokepoint_transient_does_not_mark_failed():
    """A TransientPipelineError at _transcribe → job goes back to `queued`
    (never `failed`) and the exception still propagates."""
    exc = TransientPipelineError("remote-transcription", RuntimeError("500"))
    statuses, raised = _run_pipeline_capturing(exc)

    assert JobStatus.failed not in statuses
    assert JobStatus.queued in statuses
    assert isinstance(raised, TransientPipelineError)  # propagated, not swallowed


def test_chokepoint_terminal_still_marks_failed():
    """Regression: a terminal exception (bare RuntimeError, is_transient=False)
    STILL results in status=failed with the exact str(exc) message + re-raise."""
    exc = RuntimeError("Remote transcription failed: 400 Bad Request")
    statuses, raised = _run_pipeline_capturing(exc)

    assert JobStatus.failed in statuses
    assert JobStatus.queued not in statuses
    assert isinstance(raised, RuntimeError)
    assert str(raised) == "Remote transcription failed: 400 Bad Request"


# ---------------------------------------------------------------------------
# RES-T6: Celery entry — self.retry job-level requeue (cap 2, 1m/5m/15m).
# Tests call tasks._run_generate(fake_self, "jid") directly (the refactor
# extracts the body so the Celery decorator/name stay untouched + testable).
# ---------------------------------------------------------------------------
from celery.exceptions import Retry, MaxRetriesExceededError


class FakeReq:  # stand-in for self.request
    def __init__(self, retries):
        self.retries = retries


class FakeTask:
    def __init__(self, retries=0):
        self.request = FakeReq(retries)
        self.retried = None

    def retry(self, exc=None, countdown=None, max_retries=None):
        self.retried = {"countdown": countdown, "max_retries": max_retries}
        raise Retry()


def _raiser(exc):
    async def af(_job_id):
        raise exc
    return af  # _async_pipeline is async (asyncio.run wraps it)


def test_celery_transient_calls_self_retry(monkeypatch):
    monkeypatch.setattr(
        tasks, "_async_pipeline",
        _raiser(TransientPipelineError("remote-transcription", RuntimeError("500"))),
    )
    t = FakeTask(retries=0)
    with pytest.raises(Retry):
        tasks._run_generate(t, "jid")
    assert t.retried == {"countdown": 60, "max_retries": 2}


def test_celery_second_retry_uses_next_backoff(monkeypatch):
    monkeypatch.setattr(
        tasks, "_async_pipeline",
        _raiser(TransientPipelineError("translation", RuntimeError("503"))),
    )
    t = FakeTask(retries=1)
    with pytest.raises(Retry):
        tasks._run_generate(t, "jid")
    assert t.retried["countdown"] == 300


def test_celery_caps_exhausted_marks_failed(monkeypatch):
    monkeypatch.setattr(
        tasks, "_async_pipeline",
        _raiser(TransientPipelineError("remote-transcription", RuntimeError("500"))),
    )
    marked = {}
    monkeypatch.setattr(
        tasks, "_set_job_failed_sync",
        lambda jid, msg: marked.update(jid=jid, msg=msg),
    )

    class CapTask(FakeTask):
        def retry(self, **k):
            raise MaxRetriesExceededError()

    result = tasks._run_generate(CapTask(retries=2), "jid")
    assert marked["jid"] == "jid" and "auto-retries" in marked["msg"]
    assert result == {"status": JobStatus.failed, "srt_path": None}


def test_celery_terminal_does_not_retry(monkeypatch):
    monkeypatch.setattr(
        tasks, "_async_pipeline",
        _raiser(RuntimeError("Remote transcription failed: 400 Bad Request")),
    )
    t = FakeTask()
    with pytest.raises(RuntimeError):
        tasks._run_generate(t, "jid")
    assert t.retried is None  # job already marked failed by the chokepoint


def test_translate_one_segment_propagates_TPE_not_rewrapped(monkeypatch):
    """Seam guard (final-review Critical): _post_translation_with_retries
    raises TransientPipelineError on exhausted transient; the generic
    `except Exception` in _translate_one_segment must NOT downgrade it to
    a terminal RuntimeError (that dead-ends spec §5's translation requeue)."""
    def boom(*a, **k):
        raise TransientPipelineError("translation", RuntimeError("503"))
    monkeypatch.setattr(tasks, "_translate_segment_blocking", boom)

    async def run():
        loop = asyncio.get_running_loop()
        from app.worker.usage import UsageAccumulator
        tgt = tasks._TranslateTarget(
            provider="ollama", model="gemma3:27b", mapped_model="gemma3:27b",
            base_url="http://x", api_key=None, target_language="pl",
        )
        await tasks._translate_one_segment(
            loop, {"text": "hello"}, tgt, context_pairs=None, acc=UsageAccumulator(),
        )

    with pytest.raises(TransientPipelineError) as ei:
        asyncio.run(run())
    assert ei.value.step == "translation"
