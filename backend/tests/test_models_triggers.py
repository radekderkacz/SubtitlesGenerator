import uuid
import pytest
from datetime import datetime, timezone
from app.models.orm import Trigger, TriggerEvent


def test_trigger_basic_columns():
    t = Trigger(
        id=str(uuid.uuid4()),
        name="Test",
        type="watch",
        config={"path": "/x"},
        action={"profile_name": "P1", "source_language": None, "target_language": None, "skip_if_srt": True},
        file_filter={"type": "all", "value": None},
        enabled=True,
    )
    assert t.type == "watch"
    assert t.action["profile_name"] == "P1"
    assert t.file_filter["type"] == "all"
    assert t.webhook_secret is None


def test_trigger_event_basic_columns():
    e = TriggerEvent(
        id=str(uuid.uuid4()),
        trigger_id="t1",
        fired_at=datetime.now(timezone.utc),
        event_payload={"file_path": "/x.mkv"},
        outcome="submitted",
        matched_rule_index=0,
        job_id="j1",
    )
    assert e.outcome == "submitted"
    assert e.matched_rule_index == 0
