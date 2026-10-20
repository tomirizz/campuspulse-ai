import pytest
from campuspulse import server


@pytest.mark.parametrize("mode,key,expected", [
    ("tools", "not-a-real-key", None),
    ("gemini", "not-a-real-key", "developer_api"),
    ("gemini", "", "vertex_ai"),
    ("remote", "not-a-real-key", "vertex_ai"),
])
async def test_health_reports_actual_provider_without_exposing_credentials(monkeypatch, mode, key, expected):
    monkeypatch.setenv("AGENT_MODE", mode)
    monkeypatch.setenv("GEMINI_API_KEY", key)
    value = await server.health()
    assert value["gemini_provider"] == expected
    assert "not-a-real-key" not in str(value)
    assert value["cloud_verified"] is False
