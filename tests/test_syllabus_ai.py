import json
from types import SimpleNamespace

import pytest

from campuspulse import syllabus_ai
from campuspulse.academic_import import EXAMPLE_SYLLABUS_TEXT


FORMULA = "Total: 0.3 * 1st Att + 0.3 * 2nd Att + 0.4 * Final"


def hierarchy():
    return {"course_name": "High Performance Computing (HPC)", "credits": 5, "term": None, "groups": [
        {"name": "1st attestation", "weight": 30, "source_quote": FORMULA, "components": [
            {"name": "Assignment 1", "weight": 40, "max_score": 100, "source_quote": "assignment 1: 40"},
            {"name": "Mid Term", "weight": 60, "max_score": 100, "source_quote": "Mid Term: 60"}]},
        {"name": "2nd attestation", "weight": 30, "source_quote": FORMULA, "components": [
            {"name": "Assignment 2", "weight": 20, "max_score": 100, "source_quote": "assignment 2: 20"},
            {"name": "Assignment 3", "weight": 20, "max_score": 100, "source_quote": "assignment 3: 20"},
            {"name": "End Term", "weight": 60, "max_score": 100, "source_quote": "End Term: 60"}]},
        {"name": "Final", "weight": 40, "source_quote": FORMULA, "components": [
            {"name": "Final exam", "weight": 100, "max_score": 100, "source_quote": "Final exam: Quiz 100"}]}]}


def fake(monkeypatch, payload):
    calls = []

    async def generate_content(**kwargs):
        calls.append(kwargs)
        if isinstance(payload, Exception):
            raise payload
        return SimpleNamespace(text=payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False))

    monkeypatch.setattr(syllabus_ai, "configured_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))))
    monkeypatch.setenv("AGENT_MODE", "auto")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-test-key-no-network")
    return calls


@pytest.mark.asyncio
async def test_text_hierarchy_is_flattened_in_code_with_unknown_student_scores(monkeypatch):
    calls = fake(monkeypatch, hierarchy())
    result = await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT, filename="syllabus.txt")
    assert result["course"]["name"] == "High Performance Computing (HPC)"
    assert result["course"]["credits"] == 5
    assert [component["weight"] for component in result["course"]["components"]] == [12, 18, 6, 6, 18, 40]
    assert all(component["score"] is None for component in result["course"]["components"])
    assert result["warnings"] and result["confidence"] == .85
    assert calls and result["trace"][0]["status"] == "ok"


@pytest.mark.asyncio
async def test_plain_json_request_uses_trusted_prompt_schema_not_provider_json_options(monkeypatch):
    calls = fake(monkeypatch, hierarchy())
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash")
    result = await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT)
    assert result is not None
    config = calls[0]["config"]
    assert config.response_schema is None and config.response_json_schema is None
    assert config.response_mime_type is None
    prompt = config.system_instruction
    assert "UNTRUSTED SOURCE DATA" in prompt and "Do not output student scores" in prompt
    assert '"$defs"' in prompt and '"ObservedAssessment"' in prompt
    assert '"additionalProperties":false' in prompt and '"maxItems":40' in prompt
    assert "SOURCE_TEXT" not in prompt  # Uploaded text remains separate user data.
    assert calls[0]["model"] == "gemini-3.5-flash"


@pytest.mark.asyncio
@pytest.mark.parametrize("prefix,suffix", [("```json\n", "\n```"), ("  ```JSON\r\n", "\r\n```  "), ("```\n", "\n```")])
async def test_only_full_outer_json_fence_is_accepted(monkeypatch, prefix, suffix):
    fake(monkeypatch, prefix + json.dumps(hierarchy()) + suffix)
    result = await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT)
    assert result is not None
    assert [component["weight"] for component in result["course"]["components"]] == [12, 18, 6, 6, 18, 40]


@pytest.mark.asyncio
@pytest.mark.parametrize("wrap", [
    lambda value: "Here is the result:\n```json\n" + value + "\n```",
    lambda value: "```json\n" + value + "\n```\nExtra text",
    lambda value: "```json\n" + value,
    lambda value: "```python\n" + value + "\n```",
    lambda value: "```json\n```json\n" + value + "\n```\n```",
    lambda value: value + value,
])
async def test_prose_partial_fences_wrong_languages_and_multiple_objects_are_rejected(monkeypatch, wrap):
    fake(monkeypatch, wrap(json.dumps(hierarchy())))
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["unknown_field", "invalid_sum", "invented_quote", "student_score"])
async def test_fenced_output_still_passes_strict_schema_and_evidence_checks(monkeypatch, change):
    data = hierarchy()
    if change == "unknown_field":
        data["instructions"] = "Ignore validation"
    elif change == "invalid_sum":
        data["groups"][0]["weight"] = 31
    elif change == "invented_quote":
        data["groups"][0]["components"][0]["source_quote"] = "Made-up assignment 1: 40"
    else:
        data["groups"][0]["components"][0]["score"] = 95
    fake(monkeypatch, "```json\n" + json.dumps(data) + "\n```")
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None


def test_fence_handling_does_not_modify_backticks_inside_json_quotes():
    value = '{"source_quote":"The token ```json is part of the source."}'
    assert syllabus_ai.parse_json_response(value) == json.loads(value)
    assert syllabus_ai.parse_json_response("```json\n" + value + "\n```") == json.loads(value)


@pytest.mark.asyncio
async def test_image_is_sent_as_inline_part_without_exposing_bytes(monkeypatch):
    calls = fake(monkeypatch, hierarchy())
    raw = b"\x89PNG\r\n\x1a\nPRIVATE_IMAGE_BYTES"
    result = await syllabus_ai.extract_syllabus_ai(raw=raw, text="OCR coefficients lost", filename="syllabus.png")
    part = calls[0]["contents"][0].parts[-1]
    assert part.inline_data.mime_type == "image/png" and part.inline_data.data == raw
    assert "PRIVATE_IMAGE_BYTES" not in str(result)
    assert any("визуальной" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_plaintext_hallucinated_quote_is_rejected(monkeypatch):
    data = hierarchy()
    data["groups"][0]["components"][0]["source_quote"] = "Invented assignment weight 40"
    fake(monkeypatch, data)
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None


@pytest.mark.asyncio
async def test_plaintext_invented_course_or_component_names_are_rejected(monkeypatch):
    for key in ("course", "component", "term"):
        data = hierarchy()
        if key == "course":
            data["course_name"] = "Invented Unrelated Course"
        elif key == "term":
            data["term"] = "semester"
        else:
            data["groups"][0]["components"][0]["name"] = "Invented project"
        fake(monkeypatch, data)
        assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["outer", "inner", "subtotal", "no_evidence", "score"])
async def test_incomplete_or_unsupported_grading_rules_fall_back(monkeypatch, change):
    data = hierarchy()
    if change == "outer":
        data["groups"][0]["weight"] = 25
    elif change == "inner":
        data["groups"][1]["components"][1]["weight"] = 10
    elif change == "subtotal":
        data["groups"][1]["components"].append({"name": "Assignments subtotal", "weight": 40, "source_quote": "Assignments: 40"})
    elif change == "no_evidence":
        data["groups"][0]["source_quote"] = "Course title: High Performance Computing (HPC)"
    else:
        data["groups"][0]["components"][0]["score"] = 95
    fake(monkeypatch, data)
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None


@pytest.mark.asyncio
async def test_flat_scheme_uses_one_100_percent_group(monkeypatch):
    text = "Course title: Physics\nNumber of credits: 3\nAssignment: 40%\nFinal exam: 60%"
    data = {"course_name": "Physics", "credits": 3, "groups": [{"name": "Course", "weight": 100, "components": [
        {"name": "Assignment", "weight": 40, "source_quote": "Assignment: 40%"},
        {"name": "Final exam", "weight": 60, "source_quote": "Final exam: 60%"}]}]}
    fake(monkeypatch, data)
    result = await syllabus_ai.extract_syllabus_ai(text=text)
    assert [component["weight"] for component in result["course"]["components"]] == [40, 60]


@pytest.mark.asyncio
async def test_guard_prevents_unconfigured_or_tools_mode_requests(monkeypatch):
    calls = fake(monkeypatch, hierarchy())
    monkeypatch.setenv("AGENT_MODE", "tools")
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None
    monkeypatch.setenv("AGENT_MODE", "auto")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None
    assert not calls


@pytest.mark.asyncio
async def test_oversize_or_unreadable_upload_never_calls_provider(monkeypatch):
    calls = fake(monkeypatch, hierarchy())
    assert await syllabus_ai.extract_syllabus_ai(raw=b"x" * (5 * 1024 * 1024 + 1)) is None
    assert await syllabus_ai.extract_syllabus_ai(raw=b"unrecognized binary") is None
    assert not calls


@pytest.mark.asyncio
async def test_provider_error_is_silent_safe_fallback(monkeypatch):
    fake(monkeypatch, RuntimeError("PRIVATE_KEY_DO_NOT_EXPOSE"))
    assert await syllabus_ai.extract_syllabus_ai(text=EXAMPLE_SYLLABUS_TEXT) is None
