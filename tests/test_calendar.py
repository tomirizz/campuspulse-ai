from datetime import datetime, timezone
import json
from urllib.parse import urlsplit, parse_qs

import httpx
import pytest

from campuspulse.calendar_dialogue import calendar_dialogue, parse_event
from campuspulse.dates import date_parts, aware_wall
from campuspulse.google_calendar import GoogleCalendar, CalendarError, begin_oauth, finish_oauth, token_cipher
from campuspulse.storage import SQLiteStore

NOW = datetime(2026, 10, 16, 8, tzinfo=timezone.utc)
PREFS = {"timezone": "Asia/Almaty", "event_minutes": 60}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-not-real")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret-not-real")
    return SQLiteStore(tmp_path / "db")


@pytest.mark.parametrize("text,expected", [("завтра в 13:00", "2026-10-17"), ("17.10.2026 в 13:00", "2026-10-17"), ("17 октября в 13:00", "2026-10-17"), ("2026-10-17 в 13:00", "2026-10-17")])
def test_dates(text, expected):
    assert date_parts(text, now=NOW)["date"] == expected


@pytest.mark.parametrize("text", ["31 февраля 2026 в 13:00", "17 октября в 25:00", "17 октября в 1"])
def test_invalid_dates_do_not_become_events(text):
    draft, question = parse_event("запланируй хакатон на " + text, None, PREFS, NOW)
    assert question and not draft.get("start")


def test_no_past_rollover_and_dst_rejected():
    assert parse_event("запланируй хакатон на 15 октября в 13:00", None, PREFS, NOW)[1]
    with pytest.raises(ValueError): aware_wall("2026-03-29", "02:30", "Europe/Berlin")
    with pytest.raises(ValueError): aware_wall("2026-10-25", "02:30", "Europe/Berlin")


async def test_missing_fields_multiturn_isolated_and_no_false_success(store):
    result = await calendar_dialogue("запланируй хакатон", store, "u", PREFS, NOW)
    assert "день и на какое время" in result["answer"] and result["calendar"]["status"] == "needs_details"
    assert await calendar_dialogue("в 13:00", store, "other", PREFS, NOW) is None
    result = await calendar_dialogue("17 октября", store, "u", PREFS, NOW)
    assert "какой время" in result["answer"] or "время" in result["answer"]
    invalid = await calendar_dialogue("в 25:00", store, "u", PREFS, NOW)
    assert invalid["calendar"]["status"] == "needs_details"
    result = await calendar_dialogue("в 13", store, "u", PREFS, NOW)
    assert result["calendar"]["status"] == "needs_connection" and "событие не добавлено" in result["answer"]
    assert result["calendar"]["draft"]["title"] == "хакатон"
    assert not store.list("u", "calendar_events")
    assert await calendar_dialogue("покажи мои дедлайны", store, "u", PREFS, NOW) is None
    assert await calendar_dialogue("Что было 17 октября в 13:00?", store, "u", PREFS, NOW) is None
    await calendar_dialogue("отмена", store, "u", PREFS, NOW)
    assert store.get("u", "meta", "calendar_draft") is None


async def test_complete_request_conflict_and_duplicate_id(store):
    store.put("u", "private", "google_tokens", {"encrypted": "test"})
    created = []
    class Service:
        def __init__(self, *_): pass
        async def events(self, *_):
            return {"events": [{"id": "other", "title": "Пара", "start": "2026-10-17T12:30:00+05:00", "end": "2026-10-17T13:30:00+05:00", "busy": True}]}
        async def create(self, d):
            created.append(d["event_id"])
            return {"id": d["event_id"], "title": d["title"], "start": d["start"], "end": d["end"], "status": "created", "why": {"source": "test-boundary"}}
    result = await calendar_dialogue("запланируй хакатон на 17 октября в 13:00", store, "u", PREFS, NOW, Service)
    assert result["calendar"]["status"] == "conflict" and not created
    result = await calendar_dialogue("всё равно", store, "u", PREFS, NOW, Service)
    assert result["calendar"]["status"] == "created" and len(created) == 1
    await calendar_dialogue("запланируй хакатон на 17 октября в 13:00", store, "u", PREFS, NOW, Service)
    await calendar_dialogue("всё равно", store, "u", PREFS, NOW, Service)
    assert created[0] == created[1] and len(store.list("u", "calendar_events")) == 1


async def test_google_api_contract_409_retry_and_no_invites(store, monkeypatch):
    requests = []
    draft = {"event_id": "abc123", "title": "Hack", "start": "2026-10-17T13:00:00+05:00", "end": "2026-10-17T14:00:00+05:00", "timezone": "Asia/Almaty", "messages": ["user request"], "duration_minutes": 60}
    def handler(request):
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert "attendees" not in body and request.url.params["sendUpdates"] == "none"
            assert body["start"]["timeZone"] == "Asia/Almaty"
            return httpx.Response(409)
        return httpx.Response(200, json={"id": "abc123", "summary": "Hack", "start": {"dateTime": draft["start"]}, "end": {"dateTime": draft["end"]}, "htmlLink": "https://calendar.google.com/calendar/event?eid=test"})
    async def token(*args, **kwargs): return "test-token"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = GoogleCalendar(store, "u", client)
        monkeypatch.setattr(api, "_access_token", token)
        result = await api.create(draft)
    assert result["status"] == "created" and len(requests) == 2
    assert requests[1].url.path.endswith("/abc123")


async def test_google_pagination_all_day_and_transparency(store, monkeypatch):
    def handler(req):
        if req.url.params.get("pageToken") == "next":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"nextPageToken": "next", "items": [{"id": "day", "summary": "Free", "transparency": "transparent", "start": {"date": "2026-10-17"}, "end": {"date": "2026-10-18"}}]})
    async def token(*args, **kwargs): return "test-token"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = GoogleCalendar(store, "u", client); monkeypatch.setattr(api, "_access_token", token)
        r = await api.events("2026-10-16T00:00:00+05:00", "2026-10-20T00:00:00+05:00")
    assert len(r["events"]) == 1 and not r["events"][0]["busy"]
    assert r["events"][0]["end"] == "2026-10-18T00:00:00+05:00"


async def test_oauth_pkce_state_single_use_encryption_and_isolation(store):
    url = begin_oauth(store, "u")
    params = parse_qs(urlsplit(url).query)
    assert params["code_challenge_method"] == ["S256"]
    with pytest.raises(CalendarError): await finish_oauth(store, "other", params["state"][0], "test-code")
    with pytest.raises(CalendarError): await finish_oauth(store, "u", "wrong-state", "test-code")
    def handler(request):
        assert "code_verifier=" in request.content.decode()
        return httpx.Response(200, json={"access_token": "test-token-only", "refresh_token": "test-refresh-only", "scope": "https://www.googleapis.com/auth/calendar.events.owned", "expires_in": 3600})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await finish_oauth(store, "u", params["state"][0], "test-code", client)
        with pytest.raises(CalendarError): await finish_oauth(store, "u", params["state"][0], "test-code", client)
    record = store.get("u", "private", "google_tokens")
    assert "test-token" not in json.dumps(record)
    assert json.loads(token_cipher().decrypt(record["encrypted"].encode()))["access_token"] == "test-token-only"
