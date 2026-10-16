from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from google.genai import types
import pytest

from campuspulse import server
from campuspulse.agent import gemini_run
from campuspulse.storage import SQLiteStore
from campuspulse.tools import ToolHub


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "store", SQLiteStore(tmp_path / "db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGENT_MODE", "tools")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    with TestClient(server.app) as c:
        c.get("/api/health")
        yield c


def upload(client, text, name="syllabus.txt"):
    r = client.post("/api/materials", files={"file": (name, text, "text/plain")})
    assert r.status_code == 201
    return r.json()["id"]


def test_all_six_features_through_real_routes(client):
    future = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
    mid = upload(client, f"Лабораторная: сдать {future} в 20:00\nГрадиент: вектор частных производных\nШаг обучения равен 0.01")
    sources = client.get(f"/api/materials/{mid}/syllabus").json()
    candidate = sources["candidates"][0]
    task = {"title": "Lab", "course": "ML", "estimated_minutes": 60, "due_at": candidate["due_at"], "source": candidate["source"]}
    created = client.post("/api/tasks", json=task)
    assert created.status_code == 201
    assert created.json()["source"]["quote"] == candidate["source"]["quote"]
    matches = client.post("/api/materials/search", json={"query": "шаг обучения"}).json()
    assert matches["matches"][0]["quote"] == "Шаг обучения равен 0.01"
    original = client.get("/api/workspace").json()["preferences"]
    scenario = client.post("/api/scenarios", json={"daily_minutes": 60}).json()
    assert scenario["before"] and scenario["after"] and scenario["why"]
    assert client.get("/api/workspace").json()["preferences"] == original
    config = {"confirmed": True, "target": 85, "components": [{"name": "Work", "weight": 60, "score": 80, "max_score": 100}, {"name": "Final", "weight": 40, "score": None, "max_score": 100}]}
    assert client.post("/api/grades", json=config).json()["required_score"] == "92.50"
    assert "92.50" in client.post("/api/chat", json={"message": "Какая нужна оценка?"}).json()["answer"]
    diagnostics = client.post("/api/diagnostics", json={"code": "if True print(1)"}).json()
    assert diagnostics["issues"][0]["line"] == 1 and diagnostics["why"]
    bank = client.get(f"/api/materials/{mid}/quests").json()
    chosen = next(q for q in bank["questions"] if q["answer"] == "Градиент")
    q = client.post("/api/quests", json={"material_id": mid, "question_ids": [chosen["id"]], "confirmed": True}).json()
    path = f"/api/quests/{q['id']}/answers"
    answer = {"question_id": chosen["id"], "answer": "Градиент"}
    assert client.post(path, json=answer).json()["score_percent"] == 100
    client.post(path, json=answer)
    assert client.get("/api/workspace").json()["progress"]["xp"] == 10


def test_provenance_forgery_is_rejected(client):
    mid = upload(client, "Лабораторная: 2027-10-17 в 13:00")
    source = client.get(f"/api/materials/{mid}/syllabus").json()["candidates"][0]["source"]
    source["quote"] = "Придуманный срок"
    r = client.post("/api/tasks", json={"title": "Lab", "course": "ML", "due_at": "2027-10-17T13:00:00+05:00", "source": source})
    assert r.status_code == 422 and "источник" in r.json()["detail"].lower()


def test_google_not_configured_and_tokens_never_leak(client):
    status = client.get("/api/google/status").json()
    assert not status["configured"] and not status["connected"]
    assert client.post("/api/google/connect").status_code == 422
    r = client.post("/api/chat", json={"message": "запланируй хакатон"}).json()
    assert r["mode"] == "command" and "день и на какое время" in r["answer"]
    sid = client.cookies.get("campuspulse_session")
    server.store.put(sid, "private", "google_tokens", {"encrypted": "THIS_MUST_NOT_LEAK"})
    assert "THIS_MUST_NOT_LEAK" not in client.get("/api/workspace").text
    assert "THIS_MUST_NOT_LEAK" not in client.get("/api/google/status").text
    assert client.delete("/api/workspace").status_code == 204
    assert not server.store.list(sid, "private")


def test_new_data_is_session_scoped(client):
    mid = upload(client, "Термин: определение")
    qid = client.get(f"/api/materials/{mid}/quests").json()["questions"][0]["id"]
    q = client.post("/api/quests", json={"material_id": mid, "question_ids": [qid], "confirmed": True}).json()
    client.post("/api/chat", json={"message": "запланируй хакатон"})
    with TestClient(server.app) as other:
        assert other.get(f"/api/materials/{mid}/syllabus").status_code == 404
        assert other.get(f"/api/quests/{q['id']}").status_code == 404
        assert not other.post("/api/materials/search", json={"query": "Термин"}).json()["matches"]
        assert other.post("/api/chat", json={"message": "в 13:00"}).json()["mode"] == "tools"


async def test_only_google_ai_and_read_only_model_tools():
    async with ToolHub({}) as hub:
        assert "github_issues" not in hub.specs
        assert set(hub.mcp_names) == {"current_time"}
        assert {"search_materials", "read_syllabus", "compare_plan", "grade_target", "learning_quests", "diagnose_code", "calendar_events"}.issubset(hub.specs)
        for name in ("google_calendar_insert", "shell", "execute_code", "set_grade", "propose_task"):
            assert "error" in await hub.call(name, {})


async def test_gemini_multistep_new_tools_and_invented_text_discarded():
    def response(*parts):
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))])
    responses = [response(types.Part(function_call=types.FunctionCall(name="list_materials", args={}))),
                 response(types.Part(function_call=types.FunctionCall(name="search_materials", args={"query": "скорость обучения"}))),
                 response(types.Part(text='{"fact_ids":["S2-3"],"explanation":"source_quote", "invented":"9999"}'))]
    class Models:
        async def generate_content(self, **kwargs): return responses.pop(0)
    context = {"materials": [{"id": "x", "name": "lecture.txt", "page_count": 1, "pages": [{"page": 1, "text": "Скорость обучения равна 0.01."}]}]}
    result = await gemini_run("Какая скорость обучения?", context, client=SimpleNamespace(aio=SimpleNamespace(models=Models())))
    assert "0.01" in result["answer"] and "9999" not in result["answer"]
    assert [s["tool"] for s in result["trace"]] == ["list_materials", "search_materials"]
