import pytest
from pydantic import ValidationError
from app.models.schemas import (
    ActionSchema, FileFilterSchema, TriggerCreate, TriggerEventOutcome,
)


def test_action_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ActionSchema(profile_name="P1", source_language="en", target_language="pl",
                     skip_if_srt=True, garbage="x")


def test_file_filter_basic():
    f = FileFilterSchema(type="name_contains", value="Marshals")
    assert f.type == "name_contains"
    assert f.value == "Marshals"


def test_trigger_create_watch_requires_path():
    with pytest.raises(ValidationError):
        TriggerCreate(
            name="x", type="watch", config={},
            action=ActionSchema(profile_name="P1", source_language=None,
                                target_language=None, skip_if_srt=True),
        )


def test_trigger_create_cron_requires_schedule_and_scan_path():
    with pytest.raises(ValidationError):
        TriggerCreate(
            name="x", type="cron", config={"scan_path": "/x"},
            action=ActionSchema(profile_name="P1", source_language=None,
                                target_language=None, skip_if_srt=True),
        )


def test_trigger_create_cron_requires_valid_schedule():
    with pytest.raises(ValidationError):
        TriggerCreate(
            name="x", type="cron",
            config={"scan_path": "/x", "schedule": {"mode": "daily"}},  # missing time
            action=ActionSchema(profile_name="P1", source_language=None,
                                target_language=None, skip_if_srt=True),
        )


def test_trigger_event_outcome_values():
    valid = {"submitted","skipped_no_rule","skipped_existing_srt",
             "skipped_duplicate","skipped_scan_limit","failed_dispatch"}
    for v in valid:
        assert TriggerEventOutcome(v).value == v
