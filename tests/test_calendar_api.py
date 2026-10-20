"""Calendar HTTP flows against isolated storage and mocked Google I/O only."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from campuspulse import calendar_api, server
from campuspulse.google_calendar import CalendarError
from campuspulse.storage import SQLiteStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "calendar-api.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MODE", "tools")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with TestClient(server.app) as value:
        value.get("/api/health")
        yield value


def event(**changes):
    return {
        "title": "Prepare for HPC", "start": "2030-05-01T16:00:00+05:00",
        "end": "2030-05-01T17:00:00+05:00", "description": "Review lecture notes",
        "category": "class", "busy": True, "target": "local", **changes,
    }


def create(client, **changes):
    response = client.post("/api/calendar/events", json=event(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def local_events(client):
    return client.get("/api/workspace").json()["local_events"]


def google_boundary(monkeypatch, create_call=None, events_call=None):
    monkeypatch.setattr(calendar_api, "connection_status", lambda *_: {
        "connected": True, "configured": True,
    })

    class FakeGoogle:
        def __init__(self, *_):
            pass

        async def create(self, draft):
            if create_call:
                return await create_call(draft)
            return {"id": draft["event_id"], "url": "https://calendar.google.com/calendar/event?eid=test"}

        async def events(self, start, end, timezone_name):
            if events_call:
                return await events_call(start, end, timezone_name)
            return {"events": [], "fetched_at": datetime.now(timezone.utc).isoformat()}

    monkeypatch.setattr(calendar_api, "GoogleCalendar", FakeGoogle)


def test_local_event_create_edit_delete_and_session_isolation(client):
    original = create(client)
    key = original["id"]
    assert original["kind"] == "local" and original["editable"] is True
    assert original["occurrence_count"] == 1 and original["google_status"] == "local"
    assert len(local_events(client)) == 1
    visible = client.get("/api/calendar/dashboard?month=2030-05").json()["events"]
    assert next(item for item in visible if item["id"] == key)["title"] == original["title"]

    with TestClient(server.app) as other:
        assert other.get("/api/calendar/dashboard?month=2030-05").json()["events"] == []
        assert other.put(f"/api/calendar/events/{key}", json=event()).status_code == 404
        assert other.delete(f"/api/calendar/events/{key}").status_code == 404
        assert other.post(f"/api/calendar/events/{key}/google").status_code == 404

    changed = client.put(f"/api/calendar/events/{key}", json=event(title="Updated", busy=False))
    assert changed.status_code == 200, changed.text
    assert changed.json()["id"] == key and changed.json()["busy"] is False
    assert local_events(client)[0]["title"] == "Updated"
    assert client.delete(f"/api/calendar/events/{key}").status_code == 204
    assert local_events(client) == []
    assert client.delete(f"/api/calendar/events/{key}").status_code == 404


@pytest.mark.parametrize("changes", [
    {"title": "   "}, {"category": "unknown"}, {"target": "unknown"},
    {"start": "2030-05-01T16:00:00"}, {"end": "2030-05-01T17:00:00"},
    {"end": "2030-05-01T16:00:00+05:00"},
    {"end": "2030-05-08T16:01:00+05:00"},
    {"start": "not-a-date"}, {"request_id": "not-a-valid-request"},
    {"repeat": "weekly", "repeat_until": "2030-04-30"},
    {"repeat": "weekly", "repeat_until": "2031-05-02"},
    {"repeat": "weekly", "target": "google"},
])
def test_invalid_event_or_repeat_is_rejected_without_a_saved_record(client, changes):
    result = client.post("/api/calendar/events", json=event(**changes))
    assert result.status_code == 422, result.text
    assert local_events(client) == []


@pytest.mark.parametrize("month", ["2030-00", "2030-13", "2030-5", "2030-05-01", "invalid", "9999-01"])
def test_invalid_month_has_a_validation_error(client, month):
    assert client.get("/api/calendar/dashboard", params={"month": month}).status_code == 422
    assert client.get("/api/calendar/export.ics", params={"month": month}).status_code == 422


def test_weekly_bounds_are_inclusive_and_retries_do_not_duplicate_a_series(client):
    key = "0123456789abcdef0123456789abcdef"
    payload = event(repeat="weekly", repeat_until="2030-05-15", request_id=key)
    first = client.post("/api/calendar/events", json=payload)
    assert first.status_code == 201, first.text
    result = first.json()
    assert result["id"] == key and result["occurrence_count"] == 3
    assert len({item["id"] for item in result["events"]}) == 3
    assert len({item["series_id"] for item in result["events"]}) == 1
    dates = sorted(datetime.fromisoformat(item["start"]) for item in result["events"])
    assert dates[-1].date().isoformat() == "2030-05-15"
    assert all(right - left == timedelta(days=7) for left, right in zip(dates, dates[1:]))
    retry = client.post("/api/calendar/events", json=payload)
    assert retry.status_code == 201 and retry.json()["occurrence_count"] == 3
    assert len(local_events(client)) == 3
    assert client.put(f"/api/calendar/events/{key}", json=event(repeat="weekly")).status_code == 422


def test_default_weekly_series_is_finite_and_year_boundary_is_bounded(client):
    default = create(client, repeat="weekly")
    assert default["occurrence_count"] == 8
    largest = create(client, repeat="weekly", repeat_until="2031-05-01")
    assert largest["occurrence_count"] == 53
    assert len(local_events(client)) == 61


@pytest.mark.parametrize("change", [{"title": "Different"}, {"busy": False}, {"description": "Different notes"}, {"repeat": "weekly", "repeat_until": "2030-06-01"}])
def test_request_id_rejects_payload_changes_instead_of_silently_using_old_data(client, change):
    key = "11111111111111111111111111111111"
    create(client, request_id=key)
    result = client.post("/api/calendar/events", json=event(request_id=key, **change))
    assert result.status_code == 409, result.text
    assert len(local_events(client)) == 1


def test_month_grid_and_ics_only_include_overlapping_range_with_escaped_text(client):
    label = "Лекция, часть; 1\nПовторение"
    create(client, title=label, start="2030-05-31T16:00:00+05:00", end="2030-05-31T17:00:00+05:00")
    create(client, title="Outside selected month grid", start="2030-06-15T16:00:00+05:00", end="2030-06-15T17:00:00+05:00")
    # The visible calendar includes the leading/trailing week cells.
    create(client, title="Leading week", start="2030-04-30T16:00:00+05:00", end="2030-04-30T17:00:00+05:00")
    result = client.get("/api/calendar/dashboard?month=2030-05")
    assert result.status_code == 200, result.text
    dashboard = result.json()
    assert datetime.fromisoformat(dashboard["range"]["start"]).weekday() == 0
    assert datetime.fromisoformat(dashboard["range"]["end"]).weekday() == 0
    assert {item["title"] for item in dashboard["events"]} == {label, "Leading week"}
    exported = client.get("/api/calendar/export.ics?month=2030-05")
    assert exported.status_code == 200 and "text/calendar" in exported.headers["content-type"]
    assert "attachment" in exported.headers["content-disposition"]
    unfolded = exported.text.replace("\r\n ", "")
    assert unfolded.count("BEGIN:VEVENT") == 2
    assert "Outside selected month grid" not in unfolded
    assert r"SUMMARY:Лекция\, часть\; 1\nПовторение" in unfolded
    assert all(len(line.encode("utf-8")) <= 75 for line in exported.text.split("\r\n") if line)


def test_local_busy_events_exclude_slots_in_both_regular_and_academic_plans(client):
    now = datetime.now(timezone.utc)
    begin = (now - timedelta(minutes=5)).replace(second=0, microsecond=0)
    finish = begin + timedelta(days=7)
    create(client, start=begin.isoformat(), end=finish.isoformat())
    task = client.post("/api/tasks", json={"title": "Task", "course": "HPC", "due_at": (now + timedelta(days=5)).isoformat(), "estimated_minutes": 120})
    assert task.status_code == 201, task.text
    settings = client.put("/api/preferences", json={"timezone": "UTC", "daily_minutes": 180, "start_hour": 0, "end_hour": 24})
    assert settings.status_code == 200, settings.text
    ordinary = client.get("/api/plan")
    assert ordinary.status_code == 200 and ordinary.json()["scheduled_minutes"] == 0

    course = client.post("/api/academic/courses", json={"name": "HPC", "credits": 5, "components": [{"name": "Final", "weight": 100, "due_at": (now + timedelta(days=5)).isoformat()}]})
    assert course.status_code == 201, course.text
    academic = client.get("/api/academic/plan?days=3")
    assert academic.status_code == 200 and academic.json()["scheduled_minutes"] == 0
    # A reminder marked free must not consume study availability.
    key = local_events(client)[0]["id"]
    updated = client.put(f"/api/calendar/events/{key}", json=event(start=begin.isoformat(), end=finish.isoformat(), busy=False))
    assert updated.status_code == 200
    resumed = client.get("/api/academic/plan?days=3")
    assert resumed.status_code == 200 and resumed.json()["scheduled_minutes"] > 0


def test_google_is_never_reported_created_without_a_connection(client):
    blocked = client.post("/api/calendar/events", json=event(target="google"))
    assert blocked.status_code == 409 and local_events(client) == []
    saved = create(client)
    result = client.post(f"/api/calendar/events/{saved['id']}/google")
    assert result.status_code == 409
    persisted = local_events(client)[0]
    assert persisted["google_status"] == "local" and persisted["editable"] is True


def test_google_network_retry_uses_the_same_id_and_locks_uncertain_event(client, monkeypatch):
    calls = []

    async def create_call(draft):
        calls.append(deepcopy(draft))
        if len(calls) == 1:
            raise CalendarError("Temporary network failure")
        return {"id": draft["event_id"], "url": "https://calendar.google.com/calendar/event?eid=test"}

    google_boundary(monkeypatch, create_call=create_call)
    key = "22222222222222222222222222222222"
    payload = event(target="google", request_id=key)
    first = client.post("/api/calendar/events", json=payload)
    assert first.status_code == 503
    pending = local_events(client)
    assert len(pending) == 1 and pending[0]["id"] == key
    assert pending[0]["google_status"] == "pending" and pending[0]["editable"] is False
    assert client.put(f"/api/calendar/events/{key}", json=event()).status_code == 409
    assert client.delete(f"/api/calendar/events/{key}").status_code == 409
    second = client.post("/api/calendar/events", json=payload)
    assert second.status_code == 201, second.text
    assert second.json()["google_status"] == "synced" and second.json()["editable"] is False
    assert [call["event_id"] for call in calls] == [key, key]
    assert calls[-1]["timezone"] == "Asia/Almaty"
    assert "attendees" not in calls[-1]
    assert len(local_events(client)) == 1
    assert client.post(f"/api/calendar/events/{key}/google").status_code == 200
    assert len(calls) == 2  # A third click must not create another Google event.


def test_google_snapshot_is_real_boundary_data_deduplicated_and_read_only(client, monkeypatch):
    calls = []
    saved = create(client)

    async def events_call(start, end, timezone_name):
        calls.append((start, end, timezone_name))
        return {"fetched_at": "2030-05-01T00:00:00+00:00", "events": [
            {"id": saved["id"], "title": "Remote copy", "start": saved["start"], "end": saved["end"], "busy": True},
            {"id": "remote-only", "title": "Lecture from Google", "start": "2030-05-02T09:00:00+05:00", "end": "2030-05-02T10:00:00+05:00", "busy": True},
        ]}

    google_boundary(monkeypatch, events_call=events_call)
    assert client.post(f"/api/calendar/events/{saved['id']}/google").status_code == 200
    result = client.get("/api/calendar/dashboard?month=2030-05")
    assert result.status_code == 200, result.text
    data = result.json()
    assert len(data["events"]) == 2 and calls
    assert all(item["kind"] == "google" and item["editable"] is False for item in data["events"])
    assert len([item for item in data["events"] if item["id"] == saved["id"]]) == 1
    assert calls[-1][2] == "Asia/Almaty"
    assert data["google"]["fetched_at"] == "2030-05-01T00:00:00+00:00"


def test_google_failure_returns_explicit_stale_snapshot_warning(client, monkeypatch):
    async def events_call(*_):
        raise CalendarError("Google unavailable")

    google_boundary(monkeypatch, events_call=events_call)
    sid = client.cookies.get("campuspulse_session")
    server.store.put(sid, "meta", "calendar_cache", {"fetched_at": "2030-04-30T09:00:00Z", "events": [
        {"id": "cached", "title": "Saved Google snapshot", "start": "2030-05-02T09:00:00+05:00", "end": "2030-05-02T10:00:00+05:00", "busy": True},
    ]})
    result = client.get("/api/calendar/dashboard?month=2030-05")
    assert result.status_code == 200, result.text
    assert any("Google unavailable" in warning for warning in result.json()["warnings"])
    assert result.json()["events"][0]["title"] == "Saved Google snapshot"
