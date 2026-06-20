import asyncio
from unittest.mock import AsyncMock
from app.worker import tasks


def test_run_verification_persists_verdict(monkeypatch, tmp_path):
    srt = tmp_path / "Film.en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\nHello there.\n")

    job = type("J", (), {"id": "j1", "file_path": str(tmp_path / "Film.mkv"),
                         "target_language": None, "source_language": "en",
                         "backend_profile": {}})()
    updates = {}

    async def fake_update(job_id, **fields):
        updates.update(fields); return job
    monkeypatch.setattr(tasks, "_fetch_job", AsyncMock(return_value=job))
    monkeypatch.setattr(tasks, "_update_job", fake_update)
    monkeypatch.setattr(tasks, "_publish_job_update_safe", AsyncMock())
    monkeypatch.setattr(tasks, "_verification_srt_paths", lambda j: ([str(srt)], None))

    asyncio.run(tasks.run_verification("j1"))
    assert updates["verification_status"] in ("pass", "warn", "fail")
    assert updates["verification_score"] is not None


def test_run_verification_writes_error_verdict_on_config_error(monkeypatch, tmp_path):
    """A bad profile (e.g. _resolve_litellm_target raising RuntimeError) must
    yield an 'error' verdict, never strand the job in 'running'."""
    srt = tmp_path / "Film.en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,500\nHello there.\n")
    job = type("J", (), {"id": "j1", "file_path": str(tmp_path / "Film.mkv"),
                         "target_language": None, "source_language": "en",
                         "backend_profile": {}})()
    updates = {}

    async def fake_update(job_id, **fields):
        updates.update(fields); return job
    monkeypatch.setattr(tasks, "_fetch_job", AsyncMock(return_value=job))
    monkeypatch.setattr(tasks, "_update_job", fake_update)
    monkeypatch.setattr(tasks, "_publish_job_update_safe", AsyncMock())
    monkeypatch.setattr(tasks, "_verification_srt_paths", lambda j: ([str(srt)], None))

    def boom(_job):
        raise RuntimeError("custom provider needs a URL")
    monkeypatch.setattr(tasks, "_verification_model_cfg", boom)

    asyncio.run(tasks.run_verification("j1"))
    assert updates["verification_status"] == "error"


def test_probe_duration_returns_none_on_bad_path():
    # ffprobe on a nonexistent path (or ffmpeg not importable) -> None, never raises
    assert tasks._probe_duration("/no/such/file.mkv") is None


def test_run_verification_coverage_flags_truncated(monkeypatch, tmp_path):
    """With a real video duration, a far-too-short SRT trips the coverage check."""
    srt = tmp_path / "Film.en.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi.\n")
    job = type("J", (), {"id": "j1", "file_path": str(tmp_path / "Film.mkv"),
                         "target_language": None, "source_language": "en",
                         "backend_profile": {}})()
    updates = {}

    async def fake_update(job_id, **fields):
        updates.update(fields); return job
    monkeypatch.setattr(tasks, "_fetch_job", AsyncMock(return_value=job))
    monkeypatch.setattr(tasks, "_update_job", fake_update)
    monkeypatch.setattr(tasks, "_publish_job_update_safe", AsyncMock())
    monkeypatch.setattr(tasks, "_verification_srt_paths", lambda j: ([str(srt)], None))
    monkeypatch.setattr(tasks, "_verification_model_cfg", lambda j: None)
    monkeypatch.setattr(tasks, "_probe_duration", lambda p: 600.0)  # 10min video, 2s of subs

    asyncio.run(tasks.run_verification("j1"))
    names = [c["name"] for c in updates["verification_report"]["checks"]]
    assert "coverage" in names
    assert updates["verification_status"] in ("warn", "fail")
