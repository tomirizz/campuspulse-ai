from datetime import datetime, timedelta
import random

from campuspulse.planner import calendar_export, plan_week

NOW = datetime.fromisoformat("2026-10-16T09:00:00+05:00")


def task(i="a", minutes=60, due="2026-10-17T19:00:00+05:00", **extra):
    return {"id": i, "title": "Лабораторная " + i, "course": "ML", "due_at": due,
            "estimated_minutes": minutes, "completed": False, "priority": "normal", **extra}


def test_earliest_deadline_first_and_no_overlap():
    result = plan_week([task("later"), task("first", due="2026-10-16T18:00:00+05:00")], now=NOW)
    assert result["sessions"][0]["task_id"] == "first"
    assert result["scheduled_minutes"] == 120
    for a, b in zip(result["sessions"], result["sessions"][1:]):
        assert datetime.fromisoformat(a["end"]) <= datetime.fromisoformat(b["start"])


def test_busy_hours_and_daily_budget():
    result = plan_week([task(minutes=300)], {"daily_minutes": 60, "busy": [
        {"start": "2026-10-16T16:00:00+05:00", "end": "2026-10-16T17:15:00+05:00"}]}, now=NOW)
    assert result["sessions"][0]["start"] == "2026-10-16T17:15:00+05:00"
    assert result["scheduled_minutes"] == 120
    assert result["risks"][0]["unscheduled_minutes"] == 180


def test_past_and_complete_tasks():
    result = plan_week([task("past", due="2026-10-15T18:00:00+05:00"), task("done", completed=True)], now=NOW)
    assert not result["sessions"]
    assert len(result["risks"]) == 1
    assert result["risks"][0]["task_id"] == "past"


def test_timezone_deadline_and_partial_quarter():
    result = plan_week([task(minutes=20, due="2026-10-16T11:30:00Z")], now=NOW)
    assert result["scheduled_minutes"] == 20
    assert datetime.fromisoformat(result["sessions"][-1]["end"]).hour == 16
    assert not result["risks"]


def test_no_available_time_returns_honest_risk():
    result = plan_week([task(due="2026-10-16T10:00:00+05:00")], now=NOW)
    assert result["scheduled_minutes"] == 0
    assert result["risks"][0]["unscheduled_minutes"] == 60


def test_randomized_schedule_invariants():
    rng = random.Random(43)
    tasks = [task(str(i), minutes=rng.randint(15, 200),
                  due=(NOW + timedelta(days=rng.randint(1, 6))).isoformat()) for i in range(24)]
    result = plan_week(tasks, {"daily_minutes": 180}, now=NOW)
    by_id = {t["id"]: t for t in tasks}
    spent = {}
    for session in result["sessions"]:
        start, end = datetime.fromisoformat(session["start"]), datetime.fromisoformat(session["end"])
        assert NOW <= start < end <= datetime.fromisoformat(by_id[session["task_id"]]["due_at"])
        assert 0 < session["minutes"] <= 60
        spent[start.date()] = spent.get(start.date(), 0) + session["minutes"]
    assert all(v <= 180 for v in spent.values())
    assert sum(t["estimated_minutes"] for t in tasks) == result["scheduled_minutes"] + sum(r["unscheduled_minutes"] for r in result["risks"])
    for a, b in zip(result["sessions"], result["sessions"][1:]):
        assert datetime.fromisoformat(a["end"]) <= datetime.fromisoformat(b["start"])


def test_calendar_utf8_folding_and_escape():
    result = plan_week([task(title="Задание, с; переносом\n" + "Ю" * 100)], now=NOW)
    data = calendar_export(result)
    assert all(len(line.encode()) <= 75 for line in data.split("\r\n"))
    assert "\\," in data and "\\;" in data and "\\n" in data
    assert data.count("BEGIN:VEVENT") == len(result["sessions"])
    assert "DTSTART:20261016T110000Z" in data
