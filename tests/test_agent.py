from types import SimpleNamespace

import cloudpickle
from google.genai import types
import httpx
import pytest

from campuspulse.agent import CampusPulseAgent, gemini_run
from campuspulse.mcp_server import fetch_github_issues
from campuspulse.tools import ToolHub


class FakeModels:
    """Scripted SDK boundary for contract tests, never used by the app."""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def generate_content(self, **kwargs):
        self.calls.append({**kwargs, "contents": list(kwargs["contents"])})
        return self.responses.pop(0)


def response(parts):
    return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(role="model", parts=parts))])


async def test_gemini_loop_real_mcp_with_scripted_model():
    models = FakeModels([
        response([types.Part(function_call=types.FunctionCall(id="c1", name="current_time", args={"timezone_name": "Asia/Almaty"}), thought_signature=b"test-signature")]),
        response([types.Part(function_call=types.FunctionCall(id="c2", name="list_tasks", args={}))]),
        response([types.Part(text="private thought", thought=True), types.Part(text='{"fact_ids":["S2-2"],"explanation":"observed"}')]),
    ])
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    r = await gemini_run("Дедлайны?", {"tasks": []}, client=client)
    assert "Сохранённых заданий пока нет" in r["answer"]
    assert r["grounded"] and "private thought" not in r["answer"]
    assert [t["tool"] for t in r["trace"]] == ["current_time", "list_tasks"]
    assert models.calls[1]["contents"][-2].parts[0].function_response.id == "c1"
    assert models.calls[1]["contents"][-3].parts[0].thought_signature == b"test-signature"


async def test_tools_reject_unknown_and_invalid_and_cannot_access_arbitrary_files():
    async with ToolHub({}) as hub:
        assert "error" in await hub.call("shell", {"command": "anything"})
        assert "error" in await hub.call("github_issues", {"repository": "http://localhost/secrets"})
        assert "error" in await hub.call("read_material", {"material_id": "../../etc/passwd"})


async def test_task_proposal_requires_confirmation():
    async with ToolHub({"tasks": []}) as hub:
        result = await hub.call("propose_task", {"title": "Lab", "course": "ML", "due_at": "2026-10-20T12:00:00+05:00", "estimated_minutes": 60})
        assert "error" in result and hub.proposals == []
        assert hub.context["tasks"] == []


async def test_loop_is_bounded():
    r = response([types.Part(function_call=types.FunctionCall(name="list_tasks", args={}))])
    models = FakeModels([r] * 10)
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    result = await gemini_run("repeat", {}, client=client)
    assert result["status"] == "step_limit"
    assert len(models.calls) == 8


@pytest.mark.parametrize("code", [404, 403, 429, 500])
async def test_github_failure_is_explicit(code):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(code))) as client:
        assert "error" in await fetch_github_issues("owner/repo", client)


async def test_github_filters_prs_and_keeps_sources():
    def handler(request):
        if request.url.path.endswith("/issues"):
            return httpx.Response(200, json=[{"number": 1, "title": "Lab", "html_url": "https://github.com/a/b/issues/1", "updated_at": "2026-10-16", "body": "deadline not specified"}, {"pull_request": {}, "number": 2}])
        return httpx.Response(200, json={"private": False})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await fetch_github_issues("a/b", client)
    assert len(result["issues"]) == 1 and result["fetched_at"]
    assert result["source"] == "https://github.com/a/b/issues"


def test_agent_serializes_without_credentials():
    agent = CampusPulseAgent("example-project")
    restored = cloudpickle.loads(cloudpickle.dumps(agent))
    assert restored.project == "example-project"
    assert set(vars(restored)) == {"project", "model", "location"}


@pytest.mark.live
async def test_live_github_through_mcp():
    async with ToolHub({}) as hub:
        result = await hub.call("github_issues", {"repository": "googleapis/python-genai"})
    assert "error" not in result, result
    assert result["source"] == "https://github.com/googleapis/python-genai/issues"
