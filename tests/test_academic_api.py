"""Academic features through real HTTP/session/storage and agent-tool boundaries."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
from threading import Barrier

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from campuspulse import academic_api, server
from campuspulse.academic_import import EXAMPLE_SYLLABUS_TEXT
from campuspulse.storage import SQLiteStore
from campuspulse.tools import ToolHub


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "academic.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MODE", "tools")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with TestClient(server.app) as value:
        value.get("/api/health")
        yield value


def course(**changes):
    return {"name": "High Performance Computing", "credits": 5, "target": 95,
            "components": [
                {"name": "Assignment 1", "weight": 10, "score": 75},
                {"name": "Assignment 2", "weight": 10, "score": 80},
                {"name": "Exam 1", "weight": 10},
                {"name": "Exam 2", "weight": 10},
                {"name": "Midterm", "weight": 60},
            ], **changes}


def create(client, **changes):
    response = client.post("/api/academic/courses", json=course(**changes))
    assert response.status_code == 201, response.text
    return response.json()


def test_course_crud_and_grade_edit_recalculate_saved_results(client):
    original = create(client)
    key = original["id"]
    assert original["current_average"] == 77.5
    assert original["max_achievable"] == 95.5
    assert original["active_target"] == 95
    assert len({c["id"] for c in original["components"]}) == 5
    assert client.get("/api/workspace").json()["courses"][0]["id"] == key
    first = original["components"][0]
    result = client.patch(f"/api/academic/courses/{key}/scores", json={"component_id": first["id"], "score": 60})
    assert result.status_code == 200, result.text
    assert result.json()["active_target"] == 90
    assert result.json()["max_achievable"] == 94
    read = client.get("/api/academic").json()
    assert read["courses"][0]["components"][0]["score"] == 60
    assert read["summary"]["at_risk"] == 1
    restored = client.patch(f"/api/academic/courses/{key}/scores", json={"component_id": first["id"], "score": None})
    assert restored.status_code == 200
    assert restored.json()["completed_weight"] == 10
    assert restored.json()["current_average"] == 80
    update = course(name="Updated HPC", difficulty=4)
    edited = client.put(f"/api/academic/courses/{key}", json=update)
    assert edited.status_code == 200 and edited.json()["id"] == key
    assert edited.json()["name"] == "Updated HPC" and edited.json()["difficulty"] == 4
    assert client.delete(f"/api/academic/courses/{key}").status_code == 204
    assert client.get("/api/academic").json()["courses"] == []
    assert client.delete(f"/api/academic/courses/{key}").status_code == 404


@pytest.mark.parametrize("changes", [
    {"components": [{"name": "Only", "weight": 80}]},
    {"components": [{"name": "Only", "weight": 100, "score": 101}]},
    {"components": [{"name": "Only", "weight": 100, "score": -1}]},
    {"components": [{"id": "same", "name": "A", "weight": 50}, {"id": "same", "name": "B", "weight": 50}]},
    {"components": [{"name": "Only", "weight": 100, "due_at": "2030-01-01T12:00:00"}]},
    {"credits": 0}, {"difficulty": 6}, {"unexpected": True},
])
def test_invalid_course_never_persists(client, changes):
    assert client.post("/api/academic/courses", json=course(**changes)).status_code == 422
    assert client.get("/api/academic").json()["courses"] == []


def test_invalid_score_is_atomic_and_zero_is_real_score(client):
    item = create(client)
    path = f"/api/academic/courses/{item['id']}/scores"
    component = item["components"][0]["id"]
    assert client.patch(path, json={"component_id": component, "score": 120}).status_code == 422
    assert client.get("/api/academic").json()["courses"][0]["components"][0]["score"] == 75
    assert client.patch(path, json={"component_id": "missing", "score": 0}).status_code == 404
    result = client.patch(path, json={"component_id": component, "score": 0}).json()
    assert result["completed_weight"] == 20
    assert result["earned_points"] == 8
    assert result["current_average"] == 40


@pytest.mark.parametrize("other_change", ["score", "materials"])
def test_parallel_partial_course_edits_preserve_both_changes(client, monkeypatch, other_change):
    item = create(client, components=[{"id": "a", "name": "A", "weight": 50},
                                     {"id": "b", "name": "B", "weight": 50}])
    uploaded = client.post("/api/materials", files={"file": ("lecture.txt", b"Observed learning material", "text/plain")})
    assert uploaded.status_code == 201
    material_id = uploaded.json()["id"]
    store = server.store
    original_get, original_update = store.get, store.update
    reads, updates = Barrier(2), Barrier(2)
    update_calls = []

    def synchronized_get(sid, kind, key):
        value = original_get(sid, kind, key)
        if kind == "courses" and key == item["id"]:
            # Reproduces the old implementation's two stale read snapshots.
            reads.wait(timeout=5)
        return value

    def synchronized_update(sid, kind, key, transform):
        if kind == "courses" and key == item["id"]:
            update_calls.append(key)
            updates.wait(timeout=5)
        return original_update(sid, kind, key, transform)

    monkeypatch.setattr(store, "get", synchronized_get)
    monkeypatch.setattr(store, "update", synchronized_update)
    path = f"/api/academic/courses/{item['id']}"
    second = (path + "/scores", {"component_id": "b", "score": 80}) if other_change == "score" else (
        path + "/materials", {"material_ids": [material_id]})
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.patch, path + "/scores", json={"component_id": "a", "score": 75})
        other = pool.submit(client.patch, second[0], json=second[1])
        responses = [first.result(timeout=10), other.result(timeout=10)]
    assert all(response.status_code == 200 for response in responses), [r.text for r in responses]
    saved = client.get("/api/workspace").json()["courses"][0]
    assert saved["components"][0]["score"] == 75
    assert saved["components"][1]["score"] == (80 if other_change == "score" else None)
    assert saved["material_ids"] == ([] if other_change == "score" else [material_id])
    assert len(update_calls) == 2


def test_score_patch_still_validates_materials_and_rolls_back_on_failure(client, monkeypatch):
    uploaded = client.post("/api/materials", files={"file": ("lecture.txt", b"Observed material", "text/plain")}).json()
    item = create(client, material_ids=[uploaded["id"]])
    before = client.get("/api/workspace").json()["courses"]
    original_get = server.store.get

    def missing_material(sid, kind, key):
        return None if kind == "materials" and key == uploaded["id"] else original_get(sid, kind, key)

    monkeypatch.setattr(server.store, "get", missing_material)
    response = client.patch(f"/api/academic/courses/{item['id']}/scores",
                            json={"component_id": item["components"][0]["id"], "score": 99})
    assert response.status_code == 422 and "источников" in response.json()["detail"]
    assert client.get("/api/workspace").json()["courses"] == before


def test_score_patch_does_not_persist_or_erase_schedule_derived_deadlines(client):
    item = create(client, components=[{"id": "a", "name": "Assignment 1", "weight": 60},
                                     {"id": "final", "name": "Final exam", "weight": 40}])
    due = "2030-10-25T16:00:00+05:00"
    assert client.post("/api/academic/schedule", json={"exams": [
        {"course": "High Performance Computing", "title": "Final HPC", "assessment_kind": "final", "due_at": due}]}).status_code == 200
    projected = client.get("/api/academic").json()["courses"][0]
    assert projected["components"][1]["schedule_derived"] is True
    assert projected["components"][1]["due_at"] == due
    response = client.patch(f"/api/academic/courses/{item['id']}/scores", json={"component_id": "a", "score": 75})
    assert response.status_code == 200
    saved = client.get("/api/workspace").json()["courses"][0]
    assert saved["components"][1]["due_at"] is None
    assert saved["components"][0]["score"] == 75
    after = client.get("/api/academic").json()["courses"][0]
    assert after["components"][1]["due_at"] == due and after["components"][1]["schedule_derived"] is True


def test_falling_to_the_next_goal_does_not_reduce_course_priority(client):
    item = create(client, components=[
        {"name": "First", "weight": 40, "score": 77},
        {"name": "Final", "weight": 60},
    ])
    assert item["active_target"] == 90
    result = client.patch(f"/api/academic/courses/{item['id']}/scores",
                          json={"component_id": item["components"][0]["id"], "score": 74}).json()
    assert result["active_target"] == 85
    assert result["priority_score"] > item["priority_score"]


def test_session_isolation_applies_to_reads_and_every_mutation(client):
    item = create(client)
    client.put("/api/academic/settings", json={"daily_minutes": 60})
    block = {"start": "2030-05-25T15:00:00+05:00", "end": "2030-05-25T16:00:00+05:00"}
    client.post("/api/academic/schedule", json={"busy": [block]})
    with TestClient(server.app) as other:
        state = other.get("/api/academic").json()
        assert state["courses"] == [] and state["settings"]["daily_minutes"] == 180
        assert state["imported_schedule"]["busy"] == []
        assert other.put(f"/api/academic/courses/{item['id']}", json=course()).status_code == 404
        assert other.delete(f"/api/academic/courses/{item['id']}").status_code == 404
        assert other.patch(f"/api/academic/courses/{item['id']}/scores", json={"component_id": item["components"][0]["id"], "score": 100}).status_code == 404
    assert len(client.get("/api/academic").json()["courses"]) == 1


def test_settings_persist_partial_updates_and_apply_custom_gpa(client):
    create(client)
    custom = [{"min_score": 75, "letter": "P", "gpa": 3.5, "label": "Personal pass"},
              {"min_score": 0, "letter": "F", "gpa": 0, "label": "Personal fail"}]
    result = client.put("/api/academic/settings", json={"daily_minutes": 75, "timezone": "UTC", "start_hour": 9,
                         "end_hour": 20, "preferred_target": 90, "grade_scale": custom})
    assert result.status_code == 200, result.text
    updated = client.put("/api/academic/settings", json={"daily_minutes": 120}).json()
    assert updated["timezone"] == "UTC" and updated["daily_minutes"] == 120
    assert updated["grade_scale"] == custom
    state = client.get("/api/academic").json()
    assert state["settings"]["start_hour"] == 9
    assert state["courses"][0]["grade"]["gpa"] == 3.5
    assert state["summary"]["current_gpa"] == 3.5
    for invalid in ({"daily_minutes": 0}, {"daily_minutes": 601}, {"timezone": "Bad/Zone"},
                    {"start_hour": 22, "end_hour": 9}, {"min_target": 96},
                    {"grade_scale": [{"min_score": 95, "letter": "A", "gpa": 4}]}):
        assert client.put("/api/academic/settings", json=invalid).status_code == 422
    assert client.get("/api/academic").json()["settings"] == state["settings"]


def test_syllabus_text_and_example_flatten_local_attestation_weights(client):
    for response in (client.post("/api/academic/import", json={"text": EXAMPLE_SYLLABUS_TEXT}),
                     client.get("/api/academic/example")):
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["course"]["credits"] == 5
        assert [c["weight"] for c in result["course"]["components"]] == [12, 18, 6, 6, 18, 40]
        assert all(c["score"] is None and c["source_quote"] for c in result["course"]["components"])
    # Import is a proposal: reading or parsing never creates a course silently.
    assert client.get("/api/academic").json()["courses"] == []
    parsed = client.get("/api/academic/example").json()["course"]
    assert client.post("/api/academic/courses", json=parsed).status_code == 201
    ambiguous = client.post("/api/academic/import", json={"text": "Mid Term 60\nAssignments 40"}).json()
    assert ambiguous["warnings"]
    assert not ambiguous["course"]["components"]
    assert client.post("/api/academic/import", json={"text": "text", "kind": "other"}).status_code == 422


def test_syllabus_text_file_and_image_dispatch_without_persisting(client, monkeypatch):
    file_result = client.post("/api/academic/import/file", files={"file": ("syllabus.txt", EXAMPLE_SYLLABUS_TEXT.encode(), "text/plain")})
    assert file_result.status_code == 200, file_result.text
    assert file_result.json()["extraction_method"] == "Текст файла"
    assert sum(c["weight"] for c in file_result.json()["course"]["components"]) == 100
    calls = []
    def ocr(raw, name):
        calls.append((raw, name))
        return {"text": EXAMPLE_SYLLABUS_TEXT, "method": "Test OCR", "warning": "Review OCR"}
    monkeypatch.setattr(academic_api, "extract_image", ocr)
    image_result = client.post("/api/academic/import/file", files={"file": ("syllabus.png", b"image bytes", "image/png")})
    assert image_result.status_code == 200, image_result.text
    assert calls == [(b"image bytes", "syllabus.png")]
    assert image_result.json()["extraction_method"] == "Test OCR"
    assert "Review OCR" in image_result.json()["warnings"]
    assert client.get("/api/academic").json()["courses"] == []


def test_invalid_import_files_return_clear_errors(client):
    assert client.post("/api/academic/import/file", files={"file": ("program.exe", b"abc")}).status_code == 400
    assert client.post("/api/academic/import/file", files={"file": ("large.txt", b"x" * (5 * 1024 * 1024 + 1))}).status_code == 413
    assert client.post("/api/academic/import/file", files={"file": ("bad.pdf", b"not a pdf")}).status_code == 422
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    blank = client.post("/api/academic/import/file", files={"file": ("scan.pdf", stream.getvalue())})
    assert blank.status_code == 422 and "OCR" in blank.json()["detail"]


def test_schedule_proposal_dates_and_explicit_save(client):
    text = "25.05 Mo. 15:00-16:00 Computational Mathematics C1.1.251L exam\n26.05 Tu. 09:00-10:00 Introduction to Optimization C1.3.361 exam"
    response = client.post("/api/academic/import", json={"text": text, "kind": "schedule", "year": 2030})
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert not proposal["recurring"] and len(proposal["busy"]) == 2
    assert proposal["busy"][0]["start"].startswith("2030-05-25T15:00")
    assert client.get("/api/academic").json()["imported_schedule"]["busy"] == []
    saved = client.post("/api/academic/schedule", json={"busy": proposal["busy"], "exams": proposal["exams"]})
    assert saved.status_code == 200
    state = client.get("/api/academic").json()["imported_schedule"]
    assert state["busy"] == saved.json()["busy"] and len(state["exams"]) == 2


def test_weekly_schedule_http_text_file_preview_and_metadata_save(client):
    text = "**Monday (Понедельник)**\n- **15:00-15:50** — Mathematics | lecture | C1\n**Friday**\n17:00-17:50 — Writing | practice | C2"
    args = {"kind": "schedule", "anchor_date": "2030-10-21", "weeks": 2}
    response = client.post("/api/academic/import", json={"text": text, **args})
    assert response.status_code == 200, response.text
    parsed = response.json()
    assert parsed["recurring"] and parsed["weekly_count"] == 2 and len(parsed["busy"]) == 4
    assert parsed["week_start"] == "2030-10-21" and parsed["coverage_end"] == "2030-11-03"
    assert not client.get("/api/academic").json()["imported_schedule"]["busy"]
    from_file = client.post("/api/academic/import/file", data=args,
                            files={"file": ("weekly.md", text.encode(), "text/markdown")})
    assert from_file.status_code == 200, from_file.text
    assert from_file.json()["busy"] == parsed["busy"]
    payload = {key: parsed[key] for key in ("busy", "exams", "recurring", "weekly_rules", "weekly_count", "week_start", "coverage_end", "weeks")}
    saved = client.post("/api/academic/schedule", json=payload)
    assert saved.status_code == 200, saved.text
    state = client.get("/api/academic").json()["imported_schedule"]
    assert all(state[key] == value for key, value in payload.items())
    for invalid in ({"weeks": 21}, {"anchor_date": "not a date"}):
        assert client.post("/api/academic/import", json={"text": text, **args, **invalid}).status_code == 422
        assert client.post("/api/academic/import/file", data={**args, **invalid},
                           files={"file": ("weekly.md", text.encode(), "text/markdown")}).status_code == 422


@pytest.mark.parametrize("change", [{"coverage_end": "2030-11-04"}, {"week_start": "2030-10-22"},
                                   {"weekly_count": 2}, {"weekly_rules": []}, {"weeks": 21}])
def test_weekly_metadata_must_describe_valid_bounded_repetition(client, change):
    payload = {"busy": [], "recurring": True, "weekly_rules": [
        {"weekday": 0, "start_time": "15:00", "end_time": "15:50", "title": "Maths"}],
        "weekly_count": 1, "week_start": "2030-10-21", "coverage_end": "2030-11-03", "weeks": 2}
    assert client.post("/api/academic/schedule", json={**payload, **change}).status_code == 422
    assert not client.get("/api/academic").json()["imported_schedule"]["busy"]


@pytest.mark.parametrize("busy", [
    [{"start": "2030-05-25T15:00:00", "end": "2030-05-25T16:00:00"}],
    [{"start": "2030-05-25T16:00:00Z", "end": "2030-05-25T15:00:00Z"}],
    [{"start": "invalid", "end": "invalid"}], [{"start": "2030-05-25T15:00:00Z"}],
])
def test_invalid_schedule_is_not_saved(client, busy):
    assert client.post("/api/academic/schedule", json={"busy": busy}).status_code == 422
    assert client.get("/api/academic").json()["imported_schedule"]["busy"] == []


def test_plan_rebuilds_after_scores_and_honors_imported_busy_and_day_limits(client):
    item = create(client)
    client.put("/api/academic/settings", json={"timezone": "UTC", "daily_minutes": 60, "start_hour": 0, "end_hour": 24})
    before = client.get("/api/academic/plan?days=3")
    assert before.status_code == 200, before.text
    assert before.json()["scheduled_minutes"] > 0
    assert all(day["scheduled_minutes"] <= 60 for day in before.json()["days"])
    assert client.get("/api/academic/plan?days=0").status_code == 422
    assert client.get("/api/academic/plan?days=15").status_code == 422
    now = datetime.now(timezone.utc)
    all_busy = {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=15)).isoformat(), "title": "Blocked"}
    assert client.post("/api/academic/schedule", json={"busy": [all_busy]}).status_code == 200
    blocked = client.get("/api/academic/plan?days=3").json()
    assert blocked["sessions"] == [] and blocked["risks"]
    client.post("/api/academic/schedule", json={"busy": []})
    for component in item["components"]:
        assert client.patch(f"/api/academic/courses/{item['id']}/scores", json={"component_id": component["id"], "score": 100}).status_code == 200
    completed = client.get("/api/academic/plan?days=3").json()
    assert completed["sessions"] == [] and completed["scheduled_minutes"] == 0


def test_workspace_clear_removes_all_academic_state_only_for_this_session(client):
    create(client)
    client.put("/api/academic/settings", json={"daily_minutes": 75})
    client.post("/api/academic/schedule", json={"busy": [{"start": "2030-05-25T15:00:00Z", "end": "2030-05-25T16:00:00Z"}]})
    with TestClient(server.app) as other:
        theirs = create(other, name="Other student's course")
        assert client.delete("/api/workspace").status_code == 204
        state = client.get("/api/academic").json()
        assert state["courses"] == [] and state["settings"]["daily_minutes"] == 180
        assert state["imported_schedule"]["busy"] == []
        assert other.get("/api/academic").json()["courses"][0]["id"] == theirs["id"]


async def test_academic_agent_tools_use_same_math_without_mutating_sources():
    raw = course()
    raw["id"] = "saved-course"
    context = {"courses": [raw], "academic_settings": {"timezone": "UTC", "start_hour": 0, "end_hour": 24},
               "materials": [{"id": "syllabus", "name": "HPC.txt", "pages": [{"page": 1, "text": EXAMPLE_SYLLABUS_TEXT}]}]}
    original = deepcopy(context)
    hub = ToolHub(context)
    overview = await hub.call("academic_overview", {})
    assert overview["courses"][0]["active_target"] == 95
    assert overview["courses"][0]["required_average"] == 99.375
    assert overview["why"]
    plan = await hub.call("academic_plan", {})
    assert plan["scheduled_minutes"] > 0 and plan["why"]
    parsed = await hub.call("syllabus_weights", {"material_id": "syllabus"})
    assert [c["weight"] for c in parsed["course"]["components"]] == [12, 18, 6, 6, 18, 40]
    assert "error" in await hub.call("syllabus_weights", {"material_id": "missing"})
    assert "error" in await hub.call("academic_overview", {"invented_score": 100})
    assert context == original
