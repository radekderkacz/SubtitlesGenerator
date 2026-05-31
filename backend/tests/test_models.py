from app.models.orm import Job


def test_job_has_backend_profile_column():
    col = Job.__table__.columns.get("backend_profile")
    assert col is not None
    assert col.nullable is True


def test_job_has_usage_cost_columns():
    for name in ("prompt_tokens", "completion_tokens", "total_tokens", "cost_usd"):
        col = Job.__table__.columns.get(name)
        assert col is not None, name
        assert col.nullable is True, name
