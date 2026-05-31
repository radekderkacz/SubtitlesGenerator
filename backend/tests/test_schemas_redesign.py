import pytest
from pydantic import ValidationError
from app.models.schemas import (
    ScheduleSchema, FileFilterSchema, TriggerCreate, ActionSchema,
)

def test_schedule_daily_requires_time():
    with pytest.raises(ValidationError):
        ScheduleSchema(mode="daily")
    ScheduleSchema(mode="daily", time="03:00")

def test_schedule_hourly_requires_n():
    with pytest.raises(ValidationError):
        ScheduleSchema(mode="hourly")
    ScheduleSchema(mode="hourly", every_n_hours=6)

def test_schedule_weekly_requires_day_and_time():
    with pytest.raises(ValidationError):
        ScheduleSchema(mode="weekly", time="03:00")
    ScheduleSchema(mode="weekly", day_of_week=0, time="03:00")

def test_schedule_monthly_requires_dom_and_time():
    ScheduleSchema(mode="monthly", day_of_month=1, time="03:00")
    with pytest.raises(ValidationError):
        ScheduleSchema(mode="monthly", day_of_month=31, time="03:00")  # >28

def test_file_filter_subfolder_requires_value():
    with pytest.raises(ValidationError):
        FileFilterSchema(type="subfolder", value=None)
    FileFilterSchema(type="all", value=None)
    FileFilterSchema(type="name_contains", value="Marshals")

def test_trigger_create_watch_has_action_and_filter():
    t = TriggerCreate(
        name="TV", type="watch", config={"path": "/shared/TV"},
        action=ActionSchema(profile_name="P1", source_language=None,
                            target_language=None, skip_if_srt=True),
        file_filter=FileFilterSchema(type="all", value=None),
    )
    assert t.action.profile_name == "P1"

def test_trigger_create_cron_config_takes_schedule_not_cron():
    t = TriggerCreate(
        name="Nightly", type="cron",
        config={"scan_path": "/shared/TV",
                "schedule": {"mode": "daily", "time": "03:00"}},
        action=ActionSchema(profile_name="P1", source_language=None,
                            target_language=None, skip_if_srt=True),
    )
    assert t.config["schedule"]["mode"] == "daily"
