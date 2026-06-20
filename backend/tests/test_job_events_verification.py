from datetime import datetime, timezone
from app.services.job_events import build_job_event_payload
from app.models.orm import Job


def _job(**kw):
    now = datetime.now(timezone.utc)
    base = dict(id="j1", status="completed", phase="done", progress=100, file_path="/m/a.mkv",
                error_message=None, updated_at=now,
                verification_status="pass", verification_score=92.0,
                verification_report={"summary": "ok", "checks": []}, verified_at=now)
    base.update(kw)
    return Job(**base)


def test_event_payload_includes_verification_fields():
    p = build_job_event_payload(_job())
    assert p["verification_status"] == "pass"
    assert p["verification_score"] == 92.0
    assert "verification_report" in p
    assert p["verified_at"] is not None


def test_event_payload_handles_null_verification():
    p = build_job_event_payload(_job(verification_status=None, verification_score=None,
                                     verification_report=None, verified_at=None))
    assert p["verification_status"] is None
    assert p["verified_at"] is None
