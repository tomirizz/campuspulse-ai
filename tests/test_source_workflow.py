"""A single syllabus upload is reused for grading and source-grounded notes."""
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from campuspulse import academic_api, server
from campuspulse.academic_import import EXAMPLE_SYLLABUS_TEXT, parse_syllabus
from campuspulse.storage import SQLiteStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "source-workflow.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MODE", "tools")
    with TestClient(server.app) as value:
        yield value


def test_one_syllabus_upload_links_course_and_notebook_without_duplicate_materials(client):
    parsed = client.post("/api/academic/import", json={"text": EXAMPLE_SYLLABUS_TEXT}).json()
    material_id = parsed["material_id"]
    assert parsed["course"]["material_ids"] == [material_id]
    again = client.post("/api/academic/import", json={"text": EXAMPLE_SYLLABUS_TEXT}).json()
    assert again["material_id"] == material_id
    saved = client.post("/api/academic/courses", json=parsed["course"])
    assert saved.status_code == 201, saved.text
    assert saved.json()["material_ids"] == [material_id]
    note = client.post("/api/notebooks", json={"material_ids": [material_id], "focus": "Схема оценивания"})
    assert note.status_code == 201, note.text
    assert note.json()["sources"]
    assert all(paragraph["source_ids"] for section in note.json()["sections"] for paragraph in section["paragraphs"])
    state = client.get("/api/workspace").json()
    assert len(state["materials"]) == 1
    assert client.get("/api/academic").json()["courses"][0]["material_ids"] == [material_id]
    course_id = saved.json()["id"]
    before = saved.json()["components"]
    path = f"/api/academic/courses/{course_id}/materials"
    assert client.patch(path, json={"material_ids": ["another-sessions-material"]}).status_code == 422
    linked = client.patch(path, json={"material_ids": [material_id]}).json()
    assert linked["components"] == before
    assert linked["material_ids"] == [material_id]


def test_course_cannot_link_another_sessions_source(client):
    parsed = client.post("/api/academic/import", json={"text": EXAMPLE_SYLLABUS_TEXT}).json()
    with TestClient(server.app) as other:
        response = other.post("/api/academic/courses", json=parsed["course"])
        assert response.status_code == 422
        assert other.get("/api/academic").json()["courses"] == []


def test_complete_local_scheme_skips_model(client, monkeypatch):
    async def forbidden(**kwargs):
        raise AssertionError("A complete local scheme does not need a provider")
    monkeypatch.setattr(academic_api, "extract_syllabus_ai", forbidden)
    assert client.post("/api/academic/import", json={"text": EXAMPLE_SYLLABUS_TEXT}).status_code == 200


def test_incomplete_text_can_offer_ai_proposal_without_saving_course(client, monkeypatch):
    proposal = parse_syllabus(EXAMPLE_SYLLABUS_TEXT)
    proposal["extraction_method"] = "Test Gemini"
    calls = []
    async def fake(**kwargs):
        calls.append(kwargs)
        return deepcopy(proposal)
    monkeypatch.setattr(academic_api, "extract_syllabus_ai", fake)
    response = client.post("/api/academic/import", json={"text": "Unclear table"})
    assert response.status_code == 200
    assert response.json()["extraction_method"] == "Test Gemini"
    assert calls == [{"text": "Unclear table"}]
    assert client.get("/api/academic").json()["courses"] == []


def test_image_ai_fallback_after_local_ocr_failure_is_explicit(client, monkeypatch):
    def failed(*args):
        raise ValueError("OCR unavailable")
    proposal = parse_syllabus(EXAMPLE_SYLLABUS_TEXT)
    proposal["source_text"] = EXAMPLE_SYLLABUS_TEXT
    proposal["extraction_method"] = "Test Gemini vision"
    async def fake(**kwargs):
        return deepcopy(proposal)
    monkeypatch.setattr(academic_api, "extract_image", failed)
    monkeypatch.setattr(academic_api, "extract_syllabus_ai", fake)
    response = client.post("/api/academic/import/file", files={"file": ("scan.png", b"fake", "image/png")})
    assert response.status_code == 200, response.text
    value = response.json()
    assert value["extraction_method"] == "Test Gemini vision"
    assert any("только распознанные фрагменты" in warning for warning in value["warnings"])
    assert value["material_id"]
    assert client.get("/api/academic").json()["courses"] == []
