from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from campuspulse.academic import analyze_course
from campuspulse.academic_planner import build_study_plan
from campuspulse.demo_data import create_demo, delete_demo, register_demo
from campuspulse.storage import SQLiteStore


NOW = datetime.fromisoformat("2026-10-20T18:40:00+05:00")
KINDS = ("courses", "materials", "notebooks", "local_events", "tasks", "meta")


@pytest.fixture
def store(tmp_path):
    return SQLiteStore(tmp_path / "demo.db")


def snapshot(store, sid="student"):
    return {kind: store.list(sid, kind) for kind in KINDS}


def test_empty_workspace_stays_empty_until_requested(store):
    app = FastAPI()
    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.sid = request.headers.get("X-Test-Session", "student")
        return await call_next(request)
    register_demo(app, lambda: store)
    assert all(not values for values in snapshot(store).values())
    with TestClient(app) as client:
        response = client.post("/api/academic/demo")
        assert response.status_code == 200, response.text
        assert response.json()["active"] and response.json()["status"] == "created"
        assert client.post("/api/academic/demo").json()["status"] == "already"
        other = client.delete("/api/academic/demo", headers={"X-Test-Session": "other"})
        assert other.status_code == 200 and not any(other.json()["removed"].values())
        assert len(store.list("student", "courses")) == 4
        removed = client.delete("/api/academic/demo")
        assert removed.status_code == 200 and removed.json()["removed"]["courses"] == 4
    assert all(not values for values in snapshot(store).values())


def test_demo_has_varied_grounded_courses_and_only_future_labeled_events(store):
    result = create_demo(store, "student", now=NOW)
    assert len(result["course_ids"]) == 4
    courses = store.list("student", "courses")
    analyzed = [analyze_course(value, now=NOW) for value in courses]
    hpc = next(value for value in analyzed if "HPC" in value["name"])
    maths = next(value for value in analyzed if "Mathematics" in value["name"])
    statistics = next(value for value in analyzed if "Statistics" in value["name"])
    assert hpc["current_average"] == 78 and hpc["max_achievable"] == 93.4 and hpc["active_target"] == 90
    assert maths["risk"] == "low"
    assert statistics["priority_score"] > hpc["priority_score"] > maths["priority_score"]
    assert hpc["material_ids"] and statistics["material_ids"]
    assert set(hpc["material_ids"] + statistics["material_ids"]) == set(result["material_ids"])
    assert sorted({value["credits"] for value in courses}) == [3, 5]
    for value in courses:
        assert "пример" in value["name"]
        assert sum(item["weight"] for item in value["components"]) == 100
        for assessment in value["components"]:
            if assessment["score"] is None:
                assert datetime.fromisoformat(assessment["due_at"]) > NOW
    events = store.list("student", "local_events")
    assert len(events) == 12 and all("пример" in event["title"] for event in events)
    assert all(event["busy"] and event["category"] == "class" for event in events)
    assert all(datetime.fromisoformat(event["start"]) > NOW for event in events)
    assert len({event["title"] for event in events}) == 4
    assert store.get("student", "meta", "academic_schedule") is None
    assert store.get("student", "meta", "preferences") is None


def test_demo_notebooks_have_real_selected_demo_sources(store):
    result = create_demo(store, "student", now=NOW)
    materials = {value["id"]: value for value in store.list("student", "materials")}
    assert set(materials) == set(result["material_ids"])
    notes = store.list("student", "notebooks")
    assert len(notes) == 2
    for note in notes:
        assert "пример" in note["title"]
        assert note["sources"] and note["questions"]
        for source in note["sources"]:
            assert source["quote"] in materials[source["material_id"]]["pages"][0]["text"]
        assert all("Учебный пример" not in question.get("answer", "") for question in note["questions"])


def test_demo_plan_prepares_all_subjects_without_overlapping_demo_classes(store):
    create_demo(store, "student", now=NOW)
    courses = [analyze_course(value, now=NOW) for value in store.list("student", "courses")]
    busy = [{"start": event["start"], "end": event["end"]} for event in store.list("student", "local_events")]
    plan = build_study_plan(courses, [], {"timezone": "Asia/Almaty", "daily_minutes": 180,
                                         "start_hour": 16, "end_hour": 22, "busy": busy}, now=NOW)
    assert {session["course"] for session in plan["sessions"]} == {course["name"] for course in courses}
    assert "Statistics" in plan["sessions"][0]["course"]
    for session in plan["sessions"]:
        start, end = datetime.fromisoformat(session["start"]), datetime.fromisoformat(session["end"])
        assert all(end <= datetime.fromisoformat(block["start"]) or start >= datetime.fromisoformat(block["end"]) for block in busy)


def test_remove_only_seed_ids_preserving_existing_data_and_preferences(store):
    store.put("student", "courses", "mine", {"id": "mine", "name": "My own course"})
    store.put("student", "materials", "lecture", {"id": "lecture", "name": "Own lecture"})
    store.put("student", "notebooks", "personal", {"id": "personal", "title": "Own notes"})
    store.put("student", "local_events", "meeting", {"id": "meeting", "title": "Own meeting"})
    store.put("student", "tasks", "homework", {"id": "homework", "title": "Own homework"})
    store.put("student", "meta", "preferences", {"timezone": "UTC", "daily_minutes": 90})
    store.put("student", "meta", "academic_schedule", {"busy": [{"title": "Actual classes"}], "exams": []})
    before = snapshot(store)
    result = create_demo(store, "student", now=NOW)
    assert result["active"]
    assert store.get("student", "meta", "academic_schedule") == before["meta"][0]
    delete_demo(store, "student")
    assert snapshot(store) == before
    assert not any(delete_demo(store, "student")["removed"].values())


@pytest.mark.parametrize("kind,count", [("courses", 37), ("materials", 9), ("notebooks", 49), ("local_events", 989)])
def test_capacity_failure_has_no_partial_side_effects(store, kind, count):
    for index in range(count):
        store.put("student", kind, str(index), {"id": str(index), "name": "Existing"})
    before = snapshot(store)
    with pytest.raises(ValueError, match="Недостаточно места"):
        create_demo(store, "student", now=NOW)
    assert snapshot(store) == before


def test_mid_write_failure_rolls_back_only_new_records(store, monkeypatch):
    store.put("student", "materials", "mine", {"id": "mine", "name": "Keep"})
    before = snapshot(store)
    original = store.put
    calls = 0
    def fail_once(sid, kind, key, value):
        nonlocal calls
        calls += 1
        if calls == 5:
            raise OSError("simulated disk failure")
        return original(sid, kind, key, value)
    monkeypatch.setattr(store, "put", fail_once)
    with pytest.raises(OSError):
        create_demo(store, "student", now=NOW)
    assert snapshot(store) == before


def test_parallel_requests_are_idempotent_and_sessions_independent(store):
    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(pool.map(lambda _: create_demo(store, "student", now=NOW), range(5)))
    assert sum(value["status"] == "created" for value in responses) == 1
    assert len({tuple(value["course_ids"]) for value in responses}) == 1
    assert len(store.list("student", "courses")) == 4
    other = create_demo(store, "other", now=NOW)
    assert set(other["course_ids"]).isdisjoint(responses[0]["course_ids"])
    delete_demo(store, "student")
    assert len(store.list("other", "courses")) == 4


@pytest.mark.parametrize("kind,reference", [
    ("courses", lambda mid: {"material_ids": [mid]}),
    ("notebooks", lambda mid: {"material_ids": [mid], "sources": [{"material_id": mid, "quote": "preserve"}]}),
    ("tasks", lambda mid: {"source": {"material_id": mid, "quote": "preserve"}}),
    ("quests", lambda mid: {"questions": [{"source": {"material_id": mid}}]}),
])
def test_removing_demo_preserves_seed_sources_referenced_by_personal_records(store, kind, reference):
    seed = create_demo(store, "student", now=NOW)
    mid = seed["material_ids"][0]
    source = store.get("student", "materials", mid)
    personal = {"id": "mine", **reference(mid)}
    store.put("student", kind, "mine", personal)
    result = delete_demo(store, "student")
    assert result["preserved_material_ids"] == [mid] and result["preserved"] == {"materials": 1}
    assert result["removed"]["materials"] == 1 and "личных" in result["notice"]
    assert store.get("student", "materials", mid) == source
    assert source["demo_notice"] and "пример" in source["name"]
    assert store.get("student", kind, "mine") == personal
    assert len(store.list("student", "materials")) == 1
    assert store.get("student", "meta", "academic_demo") is None
    assert not any(delete_demo(store, "student")["removed"].values())
    assert store.get("student", "materials", mid) == source


def test_demo_source_used_only_by_another_session_does_not_block_own_cleanup(store):
    seed = create_demo(store, "student", now=NOW)
    store.put("other", "courses", "mine", {"id": "mine", "material_ids": seed["material_ids"]})
    result = delete_demo(store, "student")
    assert result["removed"]["materials"] == 2 and result["preserved_material_ids"] == []
    assert not store.list("student", "materials")
    assert store.list("other", "courses")


def test_personal_grade_config_source_is_preserved(store):
    seed = create_demo(store, "student", now=NOW)
    mid = seed["material_ids"][1]
    config = {"source": {"material_id": mid, "quote": "source grading rule"}}
    store.put("student", "meta", "grade_config", config)
    result = delete_demo(store, "student")
    assert result["preserved_material_ids"] == [mid]
    assert store.get("student", "meta", "grade_config") == config


def test_personal_course_reusing_demo_source_can_still_update_scores_after_delete(tmp_path, monkeypatch):
    from campuspulse import server

    store = SQLiteStore(tmp_path / "demo-api.db")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setenv("AGENT_MODE", "tools")
    with TestClient(server.app) as client:
        seed = client.post("/api/academic/demo").json()
        material_id = seed["material_ids"][0]
        created = client.post("/api/academic/courses", json={
            "name": "My personal course", "material_ids": [material_id],
            "components": [{"id": "exam", "name": "Final exam", "weight": 100}]} )
        assert created.status_code == 201, created.text
        key = created.json()["id"]
        removed = client.delete("/api/academic/demo")
        assert removed.status_code == 200 and removed.json()["preserved_material_ids"] == [material_id]
        updated = client.patch(f"/api/academic/courses/{key}/scores", json={"component_id": "exam", "score": 80})
        assert updated.status_code == 200, updated.text
        assert updated.json()["components"][0]["score"] == 80
        assert updated.json()["material_ids"] == [material_id]
        assert client.get(f"/api/materials/{material_id}").status_code == 200
