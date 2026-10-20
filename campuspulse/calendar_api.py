"""An integrated calendar with real Google sync and an offline local workspace."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from typing import Literal
import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from campuspulse.google_calendar import GoogleCalendar, CalendarError, connection_status
from campuspulse.planner import plan_week, calendar_export


class CalendarEventInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    start: datetime
    end: datetime
    description: str = Field(default="", max_length=2000)
    category: Literal["event", "important", "class"] = "event"
    busy: bool = True
    repeat: Literal["none", "weekly"] = "none"
    repeat_until: date | None = None
    target: Literal["local", "google"] = "local"
    request_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("start", "end")
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Укажите часовой пояс события")
        return value

    @model_validator(mode="after")
    def duration(self):
        if self.end <= self.start or self.end - self.start > timedelta(days=7):
            raise ValueError("Конец должен быть позже начала; одно событие — не длиннее 7 дней")
        if self.repeat_until and (self.repeat_until < self.start.date() or self.repeat_until > self.start.date() + timedelta(days=365)):
            raise ValueError("Повторение можно задать от даты события до года вперёд")
        if self.target == "google" and self.repeat != "none":
            raise ValueError("Повторяющиеся занятия сначала сохраните в локальный календарь; отдельное событие можно отправить в Google")
        return self


def with_local_events(data):
    busy = [{"start": e["start"], "end": e["end"]} for e in data.get("local_events", []) if e.get("busy", True)]
    if not busy:
        return data
    return {**data, "preferences": {**data["preferences"], "busy": [*data["preferences"].get("busy", []), *busy]}}


def calendar_range(month, timezone_name):
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
        raise ValueError("Месяц должен быть в формате ГГГГ-ММ")
    year, number = map(int, month.split("-"))
    zone = ZoneInfo(timezone_name)
    first = datetime(year, number, 1, tzinfo=zone)
    start = first - timedelta(days=first.weekday())
    end = start + timedelta(days=42)
    return start, end


def _in_range(event, start, end):
    return datetime.fromisoformat(event["start"]) < end and datetime.fromisoformat(event["end"]) > start


def register_calendar(app, get_store, get_workspace):
    def event_for(sid, event_id):
        if not re.fullmatch(r"[0-9a-f]{32}", event_id):
            raise HTTPException(404, "Событие не найдено")
        value = get_store().get(sid, "local_events", event_id)
        if not value:
            raise HTTPException(404, "Событие не найдено в вашем календаре")
        return value

    async def send_google(sid, event):
        store = get_store()
        if not connection_status(store, sid)["connected"]:
            raise HTTPException(409, "Сначала подключите Google Calendar. Локальное событие сохранено")
        if event.get("google_status") == "synced":
            return event
        preferences = get_workspace(sid)["preferences"]
        draft = {**event, "event_id": event["id"], "timezone": preferences["timezone"],
                 "duration_minutes": round((datetime.fromisoformat(event["end"]) - datetime.fromisoformat(event["start"])).total_seconds() / 60),
                 "messages": ["Явное нажатие «Добавить в Google» в календаре CampusPulse"]}
        # Mark before I/O so a network failure can retry with the SAME Google ID.
        store.put(sid, "local_events", event["id"], {**event, "google_status": "pending", "editable": False})
        try:
            created = await GoogleCalendar(store, sid).create(draft)
        except CalendarError as exc:
            store.put(sid, "local_events", event["id"], {**event, "google_status": "pending", "editable": False})
            raise HTTPException(503, str(exc) + ". Локальная запись сохранена; повтор использует тот же ID") from exc
        result = {**event, "google_status": "synced", "google_id": created["id"],
                  "google_url": created.get("url", ""), "editable": False}
        store.put(sid, "local_events", event["id"], result)
        store.delete(sid, "meta", "calendar_cache")
        return result

    @app.post("/api/calendar/events", status_code=201)
    async def create_event(body: CalendarEventInput, request: Request):
        sid, store = request.state.sid, get_store()
        existing = store.list(sid, "local_events")
        if body.target == "google" and not connection_status(store, sid)["connected"]:
            raise HTTPException(409, "Сначала подключите Google Calendar или выберите локальное сохранение")
        zone = ZoneInfo(get_workspace(sid)["preferences"]["timezone"])
        start, end = body.start.astimezone(zone), body.end.astimezone(zone)
        canonical = {key: value for key, value in body.model_dump(mode="json").items() if key not in {"request_id", "target"}}
        canonical.update(start=start.isoformat(), end=end.isoformat())
        signature = hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if body.request_id:
            prior = store.get(sid, "local_events", body.request_id)
            if prior:
                if prior.get("_request_fingerprint") != signature:
                    raise HTTPException(409, "Этот запрос уже сохранён с другими данными. Откройте новое событие")
                if body.target == "google":
                    prior = await send_google(sid, prior)
                occurrences = [e for e in existing if prior.get("series_id") and e.get("series_id") == prior["series_id"]] or [prior]
                return {**prior, "occurrence_count": len(occurrences), "events": occurrences}
        stop = body.repeat_until or (start + timedelta(weeks=7)).date()
        values = []
        series_id = uuid.uuid4().hex if body.repeat == "weekly" else None
        while True:
            key = body.request_id if not values and body.request_id else uuid.uuid4().hex
            values.append({"id": key, "title": body.title, "start": start.isoformat(), "end": end.isoformat(),
                "description": body.description, "category": body.category, "busy": body.busy,
                "kind": "local", "editable": True, "google_status": "local", "series_id": series_id,
                "_request_fingerprint": signature,
                "created_at": datetime.now(timezone.utc).isoformat()})
            if body.repeat != "weekly" or (start + timedelta(weeks=1)).date() > stop:
                break
            start, end = start + timedelta(weeks=1), end + timedelta(weeks=1)
        if len(existing) + len(values) > 1000:
            raise HTTPException(400, "В календаре доступно до 1000 локальных событий")
        for value in values:
            store.put(sid, "local_events", value["id"], value)
        result = values[0]
        if body.target == "google":
            result = await send_google(sid, result)
            values[0] = result
        return {**result, "occurrence_count": len(values), "events": values}

    @app.put("/api/calendar/events/{event_id}")
    async def edit_event(event_id: str, body: CalendarEventInput, request: Request):
        sid, store = request.state.sid, get_store()
        old = event_for(sid, event_id)
        if old.get("google_status") in {"synced", "pending"}:
            raise HTTPException(409, "Это событие связано с Google. Проверьте или измените его непосредственно в Google Calendar")
        if body.repeat != "none":
            raise HTTPException(422, "Редактируется одно событие. Для нового повторения создайте отдельную серию")
        result = {**old, **{key: value for key, value in body.model_dump(mode="json").items()
                           if key not in {"target", "repeat", "repeat_until", "request_id"}}}
        store.put(sid, "local_events", event_id, result)
        return await send_google(sid, result) if body.target == "google" else result

    @app.delete("/api/calendar/events/{event_id}", status_code=204)
    def delete_event(event_id: str, request: Request):
        event = event_for(request.state.sid, event_id)
        if event.get("google_status") in {"synced", "pending"}:
            raise HTTPException(409, "Событие связано с Google. Удалите его в Google Calendar, чтобы избежать разных версий")
        get_store().delete(request.state.sid, "local_events", event_id)

    @app.post("/api/calendar/events/{event_id}/google")
    async def sync_event(event_id: str, request: Request):
        return await send_google(request.state.sid, event_for(request.state.sid, event_id))

    async def dashboard_data(sid, month):
        store, data = get_store(), get_workspace(sid)
        zone = data["preferences"]["timezone"]
        try:
            start, end = calendar_range(month or datetime.now(ZoneInfo(zone)).strftime("%Y-%m"), zone)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        google, warnings = connection_status(store, sid), []
        cache = data.get("calendar_cache")
        if google["connected"]:
            try:
                cache = await GoogleCalendar(store, sid).events(start.isoformat(), end.isoformat(), zone)
                store.put(sid, "meta", "calendar_cache", cache)
                data["calendar_cache"] = cache
            except CalendarError as exc:
                warnings.append(str(exc) + ". Показан последний сохранённый снимок, если он есть")
        local = [dict(e) for e in data.get("local_events", []) if _in_range(e, start, end)]
        events = local[:]
        known_google = {e.get("google_id") for e in local if e.get("google_status") == "synced"}
        for event in (cache or {}).get("events", []):
            if event["id"] in known_google or not _in_range(event, start, end):
                continue
            events.append({**event, "id": "google-" + event["id"], "kind": "google", "category": "event", "editable": False,
                           "google_url": event.get("url", ""), "google_status": "synced"})
        for event in local:
            if event.get("google_status") == "synced":
                event["kind"] = "google"
                event["editable"] = False
        for index, event in enumerate(data.get("academic_schedule", {}).get("busy", [])):
            if _in_range(event, start, end):
                events.append({**event, "id": f"imported-{index}", "kind": "imported", "category": "class", "busy": True, "editable": False})
        for task in data["tasks"]:
            if task.get("completed"):
                continue
            due = datetime.fromisoformat(task["due_at"])
            event = {"id": "deadline-" + task["id"], "title": "Сдать: " + task["title"], "start": due.isoformat(),
                     "end": (due + timedelta(minutes=15)).isoformat(), "kind": "deadline", "category": "important", "busy": False,
                     "editable": False, "description": task["course"]}
            if _in_range(event, start, end):
                events.append(event)
        from campuspulse.features_api import with_calendar
        from campuspulse.academic_api import academic_context, academic_plan
        data = with_local_events(with_calendar(data))
        if data["courses"]:
            generated = academic_plan(academic_context(store, sid, data["tasks"]), data["tasks"], data["preferences"], days=14)
        else:
            generated = plan_week(data["tasks"], data["preferences"], days=14)
        for index, session in enumerate(generated["sessions"]):
            if _in_range(session, start, end):
                events.append({**session, "id": f"study-{index}", "kind": "study", "category": "class", "busy": False,
                               "editable": False, "description": session["course"]})
        events.sort(key=lambda event: (event["start"], event["title"]))
        return {"events": events, "google": {**google, "fetched_at": (cache or {}).get("fetched_at")}, "timezone": zone,
                "range": {"start": start.isoformat(), "end": end.isoformat()}, "warnings": warnings,
                "plan_coverage": "Учебная подготовка рассчитывается на ближайшие 14 дней; личные события показываются на выбранный месяц."}

    @app.get("/api/calendar/dashboard")
    async def dashboard(request: Request, month: str | None = None):
        return await dashboard_data(request.state.sid, month)

    @app.get("/api/calendar/export.ics")
    async def export_calendar(request: Request, month: str | None = None):
        data = await dashboard_data(request.state.sid, month)
        plan = {"generated_at": datetime.now(timezone.utc).isoformat(), "sessions": [
            {**event, "task_id": event["id"], "course": event.get("description", event.get("kind", "CampusPulse"))}
            for event in data["events"]]}
        return Response(calendar_export(plan), media_type="text/calendar",
                        headers={"Content-Disposition": 'attachment; filename="campuspulse-calendar.ics"'})
