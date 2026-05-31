import pytest
from app.services.cron_scheduler import schedule_to_cron

def test_hourly():
    assert schedule_to_cron({"mode": "hourly", "every_n_hours": 6}) == "0 */6 * * *"
    assert schedule_to_cron({"mode": "hourly", "every_n_hours": 1}) == "0 */1 * * *"

def test_daily():
    assert schedule_to_cron({"mode": "daily", "time": "03:05"}) == "5 3 * * *"

def test_weekly():
    assert schedule_to_cron({"mode": "weekly", "day_of_week": 0, "time": "03:00"}) == "0 3 * * 0"

def test_monthly():
    assert schedule_to_cron({"mode": "monthly", "day_of_month": 1, "time": "23:30"}) == "30 23 1 * *"

def test_unknown_mode_raises_valueerror():
    with pytest.raises(ValueError):
        schedule_to_cron({"mode": "yearly"})
