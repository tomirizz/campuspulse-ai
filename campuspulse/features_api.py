"""Small explicit forms share the same functions as the Gemini tool registry."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from campuspulse.google_calendar import GoogleCalendar, connection_status, begin_oauth, finish_oauth
from campuspulse.models import SearchInput, ScenarioInput, GradeInput, DiagnosticInput, QuestStart, QuestAnswer
from campuspulse.study import search_materials, syllabus_candidates, scenario, grade_target, quest_candidates, diagnose, validate_source
from campuspulse.quests import start_quest, answer_quest, public_quest


async def sync_calendar(store, sid, preferences):
    now = datetime.now(timezone.utc).astimezone(ZoneInfo(preferences.get("timezone", "Asia/Almaty")))
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    value = await GoogleCalendar(store, sid).events(start.isoformat(), (start + timedelta(days=15)).isoformat(), preferences.get("timezone", "Asia/Almaty"))
    store.put(sid, "meta", "calendar_cache", value)
    return value


def with_calendar(data):
    cache = data.get("calendar_cache")
    if cache:
        data = {**data, "preferences": {**data["preferences"], "busy": [*data["preferences"].get("busy", []),
            *[{"start": e["start"], "end": e["end"]} for e in cache["events"] if e["busy"]]]}}
    return data


def register_features(app, get_store, get_workspace):
    def checked(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def material_for(sid, mid):
        m = get_store().get(sid, "materials", mid)
        if not m:
            raise HTTPException(404, "Материал не найден")
        return m

    @app.post("/api/materials/search")
    def search(body: SearchInput, request: Request):
        return search_materials(get_store().list(request.state.sid, "materials"), body.query)

    @app.get("/api/materials/{material_id}/syllabus")
    def syllabus(material_id: str, request: Request):
        return checked(syllabus_candidates, material_for(request.state.sid, material_id), get_workspace(request.state.sid)["preferences"])

    @app.post("/api/scenarios")
    async def compare(body: ScenarioInput, request: Request):
        sid, store = request.state.sid, get_store()
        data = get_workspace(sid)
        if connection_status(store, sid)["connected"]:
            try:
                data["calendar_cache"] = await sync_calendar(store, sid, data["preferences"])
            except ValueError as exc:
                raise HTTPException(503, str(exc)) from exc
        data = with_calendar(data)
        changes = body.model_dump(mode="json", exclude_none=True)
        user_changes = body.model_dump(mode="json", exclude_none=True)
        if "busy" in changes and data.get("calendar_cache"):
            changes["busy"] += [{"start": e["start"], "end": e["end"]} for e in data["calendar_cache"]["events"] if e["busy"]]
        # User input is stored separately; generated scenario output is never an input to AI math.
        result = checked(scenario, data["tasks"], data["preferences"], changes)
        store.put(sid, "meta", "scenario_input", user_changes)
        return result

    @app.post("/api/grades")
    def grade(body: GradeInput, request: Request):
        sid, store = request.state.sid, get_store()
        config = body.model_dump(mode="json")
        if config.get("source"):
            config["source"] = checked(validate_source, store.list(sid, "materials"), config["source"])
        result = checked(grade_target, config)
        store.put(sid, "meta", "grade_config", config)
        return result

    @app.post("/api/diagnostics")
    def diagnostic(body: DiagnosticInput, request: Request):
        result = checked(diagnose, **body.model_dump())
        get_store().put(request.state.sid, "meta", "diagnostic", result)
        return result

    @app.get("/api/materials/{material_id}/quests")
    def candidates(material_id: str, request: Request):
        return quest_candidates(material_for(request.state.sid, material_id))

    @app.post("/api/quests", status_code=201)
    def create_quest(body: QuestStart, request: Request):
        return checked(start_quest, get_store(), request.state.sid, material_for(request.state.sid, body.material_id), body.question_ids)

    @app.get("/api/quests/{quest_id}")
    def read_quest(quest_id: str, request: Request):
        value = get_store().get(request.state.sid, "quests", quest_id)
        if not value:
            raise HTTPException(404, "Квест не найден")
        return public_quest(value)

    @app.post("/api/quests/{quest_id}/answers")
    def submit_answer(quest_id: str, body: QuestAnswer, request: Request):
        return checked(answer_quest, get_store(), request.state.sid, quest_id, body.question_id, body.answer)

    @app.get("/api/google/status")
    def google_status(request: Request):
        return connection_status(get_store(), request.state.sid)

    @app.post("/api/google/connect")
    def connect(request: Request):
        return {"url": checked(begin_oauth, get_store(), request.state.sid)}

    @app.get("/api/google/callback")
    async def callback(request: Request, state: str = "", code: str = "", error: str = ""):
        try:
            if error or not code:
                raise ValueError("Вход Google не завершён. Разрешение не сохранено")
            await finish_oauth(get_store(), request.state.sid, state, code)
            notice = "Google Calendar подключён. Подготовленное событие можно добавить из чата или календаря."
        except ValueError as exc:
            notice = str(exc)
        get_store().put(request.state.sid, "meta", "google_notice", {"text": notice})
        # Never reflect tokens, OAuth codes, state, or upstream error descriptions in the page.
        return RedirectResponse("/#week", status_code=303)

    @app.post("/api/google/disconnect")
    async def disconnect(request: Request):
        return await GoogleCalendar(get_store(), request.state.sid).disconnect()

    @app.post("/api/calendar/sync")
    async def sync(request: Request):
        try:
            return await sync_calendar(get_store(), request.state.sid, get_workspace(request.state.sid)["preferences"])
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
