import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from campuspulse.provider_errors import classify_provider_error
from scripts import preflight


SECRET = "private-test-credential-that-must-not-be-rendered"


def error(status, message="request failed", reason=None):
    payload = {"error": {"code": status, "message": message + " " + SECRET,
                         "status": "FAILED", "details": [{"reason": reason or "UNKNOWN"}]}}
    return (ServerError if status >= 500 else ClientError)(status, payload)


@pytest.mark.parametrize("status,message,reason,expected,retryable", [
    (400, "API key not valid. Please pass a valid API key.", None, "invalid_api_key", False),
    (400, "request failed", "API_KEY_INVALID", "invalid_api_key", False),
    (400, "invalid contents", None, "invalid_request", False),
    (403, "permission denied", None, "permission_denied", False),
    (403, "User location is not supported for the API use.", None, "region_unavailable", False),
    (404, "models/unknown is not found", None, "model_not_found", False),
    (429, "quota exceeded", None, "quota_exhausted", True),
    (503, "model is overloaded", None, "temporary_unavailable", True),
    (500, "internal server error", None, "temporary_unavailable", True),
    (504, "deadline exceeded", None, "timeout", True),
])
def test_genai_sdk_errors_are_safe_and_actionable(status, message, reason, expected, retryable):
    result = classify_provider_error(error(status, message, reason), "developer_api")
    assert result["code"] == expected
    assert result["http_status"] == status
    assert result["retryable"] is retryable
    assert SECRET not in json.dumps(result)
    assert "Vertex" not in result["action"] and "IAM" not in result["action"]
    assert "billing" not in result["action"].lower()


@pytest.mark.parametrize("exception", [TimeoutError(SECRET), asyncio.TimeoutError(SECRET),
                                       httpx.ReadTimeout(SECRET), httpx.ConnectTimeout(SECRET)])
def test_timeouts_do_not_depend_on_raw_exception_text(exception):
    result = classify_provider_error(exception)
    assert result["code"] == "timeout" and result["retryable"] is True
    assert SECRET not in json.dumps(result)


def test_provider_changes_permission_and_quota_guidance():
    developer = classify_provider_error(error(403), "developer_api")
    vertex = classify_provider_error(error(403), "vertex_ai")
    assert "Google AI Studio" in developer["action"]
    assert "IAM" in vertex["action"]
    assert "Vertex AI" in classify_provider_error(error(429), "vertex_ai")["action"]
    assert "бесплатного тарифа" in classify_provider_error(error(429), "developer_api")["action"]


def test_alternative_status_attribute_and_no_error_stringification():
    class UnsafeError(Exception):
        response = SimpleNamespace(status_code=503)

        def __str__(self):
            raise AssertionError("Raw exception must never be rendered")

    result = classify_provider_error(UnsafeError())
    assert result["code"] == "temporary_unavailable" and result["http_status"] == 503
    assert classify_provider_error(ValueError(SECRET))["code"] == "provider_error"
    with pytest.raises(ValueError, match="Unsupported Gemini provider"):
        classify_provider_error(UnsafeError(), "unsupported")


class FakeHub:
    mcp_names = {"current_time"}

    def __init__(self, context):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def call(self, name, arguments):
        return {"now": "2026-10-20T17:00:00+05:00"}


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(400, "invalid_api_key"), (403, "permission_denied"),
                                            (404, "model_not_found"), (429, "quota_exhausted"),
                                            (503, "temporary_unavailable")])
async def test_preflight_uses_developer_api_guidance_without_network(monkeypatch, capsys, status, expected):
    closed = []

    async def generate_content(**kwargs):
        raise error(status, "API key not valid" if status == 400 else "request failed")

    async def close_async():
        closed.append("async")

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content),
                                                aclose=close_async), close=lambda: closed.append("sync"))
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(preflight, "ToolHub", FakeHub)
    monkeypatch.setattr(preflight, "configured_client", lambda: client)
    assert await preflight.check(True) is False
    output = capsys.readouterr().out
    checks = json.loads(output)
    live = checks[-1]
    assert live["provider"] == "developer_api" and live["code"] == expected
    assert SECRET not in output
    assert "Vertex" not in live["action"] and "IAM" not in live["action"]
    assert closed == ["async", "sync"]


@pytest.mark.asyncio
async def test_preflight_vertex_uses_iam_guidance_without_network(monkeypatch, capsys):
    import google.auth

    async def generate_content(**kwargs):
        raise error(403)

    async def close_async():
        pass

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(google.auth, "default", lambda **kwargs: (SimpleNamespace(refresh=lambda request: None), "test-project"))
    monkeypatch.setattr(preflight, "ToolHub", FakeHub)
    monkeypatch.setattr(preflight, "configured_client", lambda: SimpleNamespace(
        aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content), aclose=close_async), close=lambda: None))
    assert await preflight.check(True) is False
    live = json.loads(capsys.readouterr().out)[-1]
    assert live["provider"] == "vertex_ai" and live["code"] == "permission_denied"
    assert "IAM" in live["action"] and SECRET not in json.dumps(live)
