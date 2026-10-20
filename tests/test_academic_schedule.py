from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from campuspulse import server
from campuspulse.academic_schedule import apply_exam_schedule
from campuspulse.storage import SQLiteStore


NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)


def course():
    return {"id": "hpc", "name": "High Performance Computing (HPC)", "credits": 5,
            "components": [{"id": "one", "name": "Assignment 1", "weight": 60, "score": 80, "max_score": 100},
                           {"id": "two", "name": "Final exam", "weight": 40, "score": None, "max_score": 100}]}


def exam(**updates):
    return {"course": "HPC", "title": "Экзамен HPC", "due_at": (NOW + timedelta(days=3)).isoformat(),
            "assessment_kind": "final", **updates}


def test_exact_acronym_link_never_mutates_original():
    original = course()
    snapshot = deepcopy(original)
    projections, notes = apply_exam_schedule([original], {"exams": [exam()]}, NOW)
    assert original == snapshot
    assert projections[0]["components"][1]["due_at"] == exam()["due_at"]
    assert projections[0]["_schedule_links"] and not notes


@pytest.mark.parametrize("exam_patch", [{"course": "Wrong course"}, {"assessment_kind": "exam"}])
def test_ambiguous_or_unknown_exam_does_not_invent_assessment(exam_patch):
    projections, notes = apply_exam_schedule([course()], {"exams": [exam(**exam_patch)]}, NOW)
    assert not projections[0]["components"][1].get("due_at")
    assert notes


def test_duplicate_course_name_and_explicit_deadline_preserved():
    value = course()
    value["components"][1]["due_at"] = (NOW + timedelta(days=1)).isoformat()
    projections, _ = apply_exam_schedule([value], {"exams": [exam()]}, NOW)
    assert projections[0]["components"][1]["due_at"] == value["components"][1]["due_at"]
    projections, notes = apply_exam_schedule([course(), course()], {"exams": [exam()]}, NOW)
    assert notes and all(not c["components"][1].get("due_at") for c in projections)


def test_repeated_exam_uses_nearest_future_not_past():
    exams = [exam(due_at=(NOW - timedelta(days=1)).isoformat()), exam(), exam(due_at=(NOW + timedelta(days=7)).isoformat())]
    projections, notes = apply_exam_schedule([course()], {"exams": exams}, NOW)
    assert projections[0]["components"][1]["due_at"] == exam()["due_at"]
    assert notes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "schedule.db"))
    monkeypatch.setenv("AGENT_MODE", "tools")
    with TestClient(server.app) as value:
        value.get("/api/health")
        yield value


def test_schedule_links_exam_and_calendar_ics_and_settings_stay_in_sync(client):
    value = course()
    value.pop("id")
    created = client.post("/api/academic/courses", json=value)
    assert created.status_code == 201
    due = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    assert client.post("/api/academic/schedule", json={"busy": [], "exams": [exam(due_at=due)]}).status_code == 200
    loaded = client.get("/api/academic").json()["courses"][0]
    assert loaded["schedule_links"] and datetime.fromisoformat(loaded["components"][1]["due_at"]) == datetime.fromisoformat(due)
    raw = client.get("/api/workspace").json()["courses"][0]
    assert not raw["components"][1]["due_at"]  # Derived date stays separate from saved syllabus.
    plan = client.get("/api/plan")
    assert plan.status_code == 200 and plan.json()["sessions"]
    assert all(s["why"] for s in plan.json()["sessions"])
    assert "BEGIN:VEVENT" in client.get("/api/plan/calendar.ics").text
    settings = client.put("/api/academic/settings", json={"daily_minutes": 15, "start_hour": 19, "end_hour": 22})
    assert settings.status_code == 200
    prefs = client.get("/api/workspace").json()["preferences"]
    assert prefs["daily_minutes"] == 15 and prefs["start_hour"] == 19
    prefs["daily_minutes"] = 90
    assert client.put("/api/preferences", json=prefs).status_code == 200
    assert client.get("/api/academic").json()["settings"]["daily_minutes"] == 90


@pytest.mark.parametrize("patch", [{"due_at": "not a date"}, {"due_at": "2026-10-20T12:00:00"}, {"assessment_kind": "unknown"}])
def test_exam_bad_dates_cannot_be_saved(client, patch):
    assert client.post("/api/academic/schedule", json={"exams": [exam(**patch)]}).status_code == 422
