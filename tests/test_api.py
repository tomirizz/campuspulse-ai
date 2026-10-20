from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from pypdf import PdfWriter
import pytest

from campuspulse import server
from campuspulse.storage import SQLiteStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "test.db"))
    monkeypatch.setenv("AGENT_MODE", "tools")
    with TestClient(server.app) as c:
        c.get("/api/health")
        yield c


def data(**updates):
    return {"title": "ML lab", "course": "ML", "due_at": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(), "estimated_minutes": 90, **updates}


def test_task_crud_and_persistence(client):
    r = client.post("/api/tasks", json=data())
    assert r.status_code == 201
    key = r.json()["id"]
    assert len(client.get("/api/workspace").json()["tasks"]) == 1
    assert client.put("/api/tasks/" + key, json=data(title="Changed")).json()["title"] == "Changed"
    assert client.patch("/api/tasks/" + key, json={"completed": True}).json()["completed"]
    assert not client.get("/api/plan").json()["sessions"]
    assert client.delete("/api/tasks/" + key).status_code == 204
    assert not client.get("/api/workspace").json()["tasks"]


def test_sessions_are_isolated(client):
    key = client.post("/api/tasks", json=data()).json()["id"]
    with TestClient(server.app) as other:
        assert not other.get("/api/workspace").json()["tasks"]
        assert other.patch("/api/tasks/" + key, json={"completed": True}).status_code == 404
        assert other.delete("/api/tasks/" + key).status_code == 404


@pytest.mark.parametrize("patch", [{"title": " "}, {"estimated_minutes": -2}, {"due_at": "2026-10-17T12:00:00"}, {"priority": "invalid"}, {"evil": "extra"}])
def test_task_validation(client, patch):
    assert client.post("/api/tasks", json=data(**patch)).status_code == 422


def test_cross_origin_and_security_headers(client):
    assert client.post("/api/tasks", json=data(), headers={"Origin": "https://attacker.test"}).status_code == 403
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Cache-Control"] == "no-store"


def test_text_material_read_delete_isolation(client):
    r = client.post("/api/materials", files={"file": ("lecture.txt", "Gradient descent: update weights.", "text/plain")})
    assert r.status_code == 201
    key = r.json()["id"]
    assert "Gradient" in client.get("/api/materials/" + key).json()["pages"][0]["text"]
    with TestClient(server.app) as other:
        assert other.get("/api/materials/" + key).status_code == 404
    assert client.delete("/api/materials/" + key).status_code == 204


@pytest.mark.parametrize("name,raw,status", [("evil.exe", b"abc", 400), ("bad.pdf", b"not a PDF", 400), ("empty.txt", b"", 400), ("large.txt", b"x" * (5 * 1024 * 1024 + 1), 413)], ids=["extension", "invalid-pdf", "empty", "oversized"])
def test_invalid_materials(client, name, raw, status):
    assert client.post("/api/materials", files={"file": (name, raw)}).status_code == status


def test_scanned_pdf_is_not_claimed_readable(client):
    w = PdfWriter(); w.add_blank_page(width=100, height=100)
    buffer = BytesIO(); w.write(buffer)
    r = client.post("/api/materials", files={"file": ("scan.pdf", buffer.getvalue(), "application/pdf")})
    assert r.status_code == 400 and "OCR" in r.json()["detail"]


def test_plan_calendar_and_preferences(client):
    client.post("/api/tasks", json=data())
    assert client.put("/api/preferences", json={"start_hour": 20, "end_hour": 10}).status_code == 422
    assert client.put("/api/preferences", json={"timezone": "invalid"}).status_code == 422
    assert client.get("/api/plan").json()["scheduled_minutes"] == 90
    assert "BEGIN:VEVENT" in client.get("/api/plan/calendar.ics").text


def test_clear_workspace(client):
    client.post("/api/tasks", json=data())
    assert client.delete("/api/workspace").status_code == 204
    assert not client.get("/api/workspace").json()["tasks"]


def test_tools_chat_uses_real_mcp(client):
    client.post("/api/tasks", json=data())
    r = client.post("/api/chat", json={"message": "Составь план недели"})
    assert r.status_code == 200, r.text
    value = r.json()
    assert value["mode"] == "tools" and value["model"] is None
    assert value["trace"][0]["tool"] == "current_time"
    assert value["trace"][0]["transport"] == "MCP · stdio"
    assert value["plan"]["scheduled_minutes"] == 90
    assert len(client.get("/api/workspace").json()["history"]) == 2


def test_gemini_missing_credentials_never_falls_back(client, monkeypatch):
    monkeypatch.setenv("AGENT_MODE", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    r = client.post("/api/chat", json={"message": "План недели"})
    assert r.status_code == 503
    assert not client.get("/api/workspace").json()["history"]


def test_reward_api_idempotent_and_edit_frozen(client):
    t=client.post('/api/tasks',json=data(estimated_minutes=90)).json()
    path='/api/tasks/'+t['id']
    for _ in range(3):client.patch(path,json={'completed':True})
    w=client.get('/api/workspace').json()
    assert w['progress']['xp']==35 and len(w['progress']['ledger'])==1
    client.put(path,json=data(estimated_minutes=2400))
    assert client.get('/api/workspace').json()['progress']['xp']==35
    client.patch(path,json={'completed':False})
    assert client.get('/api/workspace').json()['progress']['xp']==0
    client.patch(path,json={'completed':True})
    assert client.get('/api/workspace').json()['progress']['xp']==35
    client.delete(path)
    assert client.get('/api/workspace').json()['progress']['xp']==0


def test_explanations_accompany_results_and_errors(client):
    task=client.post('/api/tasks',json=data()).json()
    assert task['why']['inputs']['оценка минут']==90
    plan=client.get('/api/plan').json()
    assert plan['why']['result']==90
    assert all('why' in s for s in plan['sessions'])
    error=client.post('/api/tasks',json=data(estimated_minutes=-1))
    assert error.status_code==422 and error.json()['why']['source']
    r=client.post('/api/chat',json={'message':'Составь план недели'}).json()
    assert r['why']['source'] and r['evidence']
    h=client.get('/api/workspace').json()['history'][-1]
    assert h['evidence']==r['evidence'] and h['why']==r['why']
