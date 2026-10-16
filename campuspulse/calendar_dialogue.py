"""Write actions are authorized by explicit user messages, never by document text or LLM output."""
from datetime import datetime, timedelta, timezone
import hashlib
import re
import time

from campuspulse.dates import date_parts, DATE_RE, TIME_RE, aware_wall
from campuspulse.google_calendar import GoogleCalendar, CalendarError, connection_status
from campuspulse.progress import proof

INTENT = re.compile(r"^(?:пожалуйста[,]?\s+)?(?:запланируй|запланировать|создай(?:\s+событие)?|добавь(?:\s+событие)?(?:\s+в\s+(?:гугл\s+|google\s+)?календарь)?)\s+", re.I)


def event_intent(message):
    return bool(INTENT.search(message.strip())) and not bool(re.search(r"(?:учебн\w*\s+недел|план\s+недел|мою\s+неделю|^(?:добавь|создай)\s+(?:задание|миссию|задачу))", message, re.I))


def date_reply(message):
    """A date mentioned in an unrelated question is not permission to finish a write."""
    remainder = DATE_RE.sub("", message.lower())
    remainder = TIME_RE.sub("", remainder)
    remainder = re.sub(r"\b\d{1,2}:\d{2}\b", "", remainder)
    remainder = re.sub(r"\bв\s+\d{1,2}(?:\s*(?:утра|дня|вечера|ночи|часов?))?\b", "", remainder)
    remainder = re.sub(r"\b\d{1,4}\s*(?:минут\w*|час\w*)\b", "", remainder)
    remainder = re.sub(r"\b(?:сегодня|завтра|послезавтра|на|в|с|давай|лучше|пожалуйста|года?|по|москве|московскому|времени|мск|utc|утра|дня|вечера|ночи)\b", "", remainder)
    return not remainder.strip(" .,!?;\n")


def parse_event(message, pending, preferences, now=None):
    now = now or datetime.now(timezone.utc)
    new = event_intent(message)
    tz = preferences.get("timezone", "Asia/Almaty") if new else (pending or {}).get("timezone", preferences.get("timezone", "Asia/Almaty"))
    if re.search(r"по москве|московск|\bмск\b", message, re.I):
        tz = "Europe/Moscow"
    elif re.search(r"\bUTC\b", message, re.I):
        if re.search(r"UTC\s*[+-]", message, re.I):
            return dict(pending or {"messages": [message]}), "Для смещения UTC укажите часовой пояс в настройках и повторите запрос. Смещение из предположений не используется."
        tz = "UTC"
    draft = {"timezone": tz, "duration_minutes": preferences.get("event_minutes", 60), "messages": []} if new else dict(pending or {})
    draft["messages"] = [*draft.get("messages", []), message][-12:]
    draft["timezone"] = tz
    draft.setdefault("duration_minutes", preferences.get("event_minutes", 60))
    parts = date_parts(message, tz, now)
    lower = message.lower().strip()
    if len(DATE_RE.findall(message)) > 1 or len(TIME_RE.findall(message)) > 1 or re.search(r"\bкажд(?:ый|ую|ое|ые)\b", lower):
        return draft, "Укажите одно событие с одной датой и временем начала. Повторения и диапазоны через чат пока не поддерживаются."
    if new:
        body = INTENT.sub("", message.strip(), count=1)
        quoted = re.match(r'[«"]([^»"]+)[»"]', body)
        if quoted:
            title = quoted[1]
        else:
            candidates = [m.start() for m in (DATE_RE.search(body), TIME_RE.search(body), re.search(r"\s+(?:на\s+(?:\d|сегодня|завтра|послезавтра|понедельник|вторник|среду|четверг|пятницу|субботу|воскресенье)|в\s+\d|сегодня\b|завтра\b|послезавтра\b)", body, re.I)) if m]
            title = body[:min(candidates)] if candidates else body
            title = re.sub(r"\s+(?:на|в|с)\s*$", "", title)
        draft["title"] = title.strip(" .,!?:;")[:160]
    if parts["error"]:
        return draft, parts["error"]
    if parts["date"] or parts["time"] or re.search(r"\bна\s+\d+\s*(?:час|минут)", lower):
        for key in ("start", "end", "event_id", "conflict_signature"):
            draft.pop(key, None)
    if parts["date"]:
        draft["date"] = parts["date"]
    if parts["time"]:
        draft["time"] = parts["time"]
    duration = re.search(r"\bна\s+(\d{1,4})\s*(минут\w*|час\w*)\b", lower)
    if duration:
        value = int(duration[1]) * (60 if duration[2].startswith("час") else 1)
        if not 5 <= value <= 1440:
            return draft, "Длительность события должна быть от 5 минут до 24 часов."
        draft["duration_minutes"] = value
    if not draft.get("title") or draft["title"].lower() in {"событие", "в календарь", "на", "в", "с", "завтра", "сегодня", "послезавтра"}:
        return draft, "Как назвать событие? Напишите, например: «запланируй хакатон»."
    missing = [label for field, label in (("date", "день"), ("time", "время")) if not draft.get(field)]
    if missing:
        question = "На какой день и на какое время" if len(missing) == 2 else "На какой день" if missing == ["день"] else "На какое время"
        return draft, f"{question} запланировать «{draft['title']}»? Например: 17 октября 2026 в 13:00. Часовой пояс: {tz}."
    try:
        start = aware_wall(draft["date"], draft["time"], tz)
    except ValueError as exc:
        return draft, str(exc)
    if start <= now:
        return draft, "Указанное начало уже прошло. Уточните будущую дату, год и время; переносить событие на другой год автоматически я не буду."
    draft.update(start=start.isoformat(), end=(start + timedelta(minutes=draft["duration_minutes"])).isoformat())
    return draft, None


def command_result(answer, why, trace, calendar=None):
    return {"answer": answer, "why": why, "trace": trace, "mode": "command", "model": None,
            "status": "ok", "grounded": True, "evidence": [], "proposals": [], "plan": None, "calendar": calendar}


async def calendar_dialogue(message, store, sid, preferences, now=None, service_factory=GoogleCalendar):
    pending = store.get(sid, "meta", "calendar_draft")
    new = event_intent(message)
    lower = message.strip().lower().rstrip(".!?")
    followup = bool(pending) and (date_reply(message) or lower in {"сохрани", "добавь", "повтори", "всё равно", "все равно", "отмена", "отмени", "отменить"})
    if not new and not followup:
        return None
    trace = []
    def record(tool, label, arguments, result, started=None):
        trace.append({"step": len(trace) + 1, "tool": tool, "label": label, "transport": "Google Calendar API" if tool.startswith("google_") else "Custom Function",
                      "selection": "Явная команда пользователя → проверяемые правила", "arguments": arguments,
                      "result": result, "status": "error" if result.get("error") else "ok", "elapsed_ms": round((time.monotonic() - started) * 1000) if started else 0})
    if lower in {"отмена", "отмени", "отменить"}:
        store.delete(sid, "meta", "calendar_draft")
        why = proof("Почему действие отменено", "явная команда пользователя → удалить незавершённый запрос", {"сообщение": message}, "Запрос отменён", "Ваше сообщение", "Существующие события Google не удаляются.")
        record("cancel_calendar_draft", "Отменяю незавершённый запрос", {}, {"why": why})
        return command_result("Запрос на создание отменён. Существующие события в Google Calendar сохранены.", why, trace)
    draft, question = parse_event(message, pending, preferences, now)
    why = proof("Откуда параметры события", "явные дата и время из диалога; конец = начало + длительность; год без указания = текущий год",
                {"сообщения": draft["messages"], "часовой пояс": draft.get("timezone"), "длительность по настройке": preferences.get("event_minutes", 60)},
                {k: draft.get(k) for k in ("title", "date", "time", "duration_minutes")}, "Ваши сообщения + настройки календаря",
                "Неполные и прошедшие даты требуют уточнения. Длительность без указания берётся из сохранённой настройки.")
    record("parse_calendar_request", "Проверяю название, дату и время", {"message": message}, {"parameters": why["result"], "question": question, "why": why})
    store.put(sid, "meta", "calendar_draft", draft)
    if question:
        return command_result(question, why, trace, {"status": "needs_details", "draft": draft})
    # Stable ID survives repeated chat turns, network retries and process restarts.
    draft["event_id"] = hashlib.sha256((sid + "\n" + draft["title"].casefold() + "\n" + draft["start"] + "\n" + draft["end"]).encode()).hexdigest()
    store.put(sid, "meta", "calendar_draft", draft)
    if not connection_status(store, sid)["connected"]:
        answer = f"Подготовлено: «{draft['title']}», {draft['date']} в {draft['time']} ({draft['timezone']}), {draft['duration_minutes']} мин.\nGoogle Calendar ещё не подключён — событие не добавлено. Подключите его в настройках, затем нажмите «Добавить подготовленное событие» или напишите «сохрани»."
        return command_result(answer, why, trace, {"status": "needs_connection", "draft": draft})
    service = service_factory(store, sid)
    try:
        started = time.monotonic()
        observed = await service.events(draft["start"], draft["end"], draft["timezone"])
        record("google_calendar_list", "Проверяю занятость в Google Calendar", {"start": draft["start"], "end": draft["end"]}, observed, started)
        conflicts = [e for e in observed["events"] if e["busy"] and e["id"] != draft["event_id"] and
                     datetime.fromisoformat(e["start"]) < datetime.fromisoformat(draft["end"]) and
                     datetime.fromisoformat(e["end"]) > datetime.fromisoformat(draft["start"])]
        signature = hashlib.sha256("|".join(sorted(e["id"] + e["start"] + e["end"] for e in conflicts)).encode()).hexdigest()
        override = lower in {"всё равно", "все равно"} and pending and pending.get("conflict_signature") == signature
        if conflicts and not override:
            draft["conflict_signature"] = signature
            store.put(sid, "meta", "calendar_draft", draft)
            titles = "; ".join(e["title"] for e in conflicts)
            why = proof("Почему уточняю время", "пересечение: начало A < конец B и конец A > начало B", {"событие": why["result"], "занято": conflicts}, "Пересечение", "Google Calendar events.list")
            return command_result(f"Это время пересекается с: {titles}. Выберите другое время или напишите «всё равно», чтобы добавить с пересечением.", why, trace, {"status": "conflict", "draft": draft})
        started = time.monotonic()
        created = await service.create(draft)
        record("google_calendar_insert", "Добавляю событие в Google Calendar", {k: draft[k] for k in ("title", "start", "end", "event_id")}, created, started)
        store.put(sid, "calendar_events", created["id"], created)
        store.delete(sid, "meta", "calendar_draft")
        # Invalidate the planner's cache; next calendar refresh reads authoritative state.
        store.delete(sid, "meta", "calendar_cache")
        answer = f"В Google Calendar добавлено «{created['title']}»: {draft['date']} в {draft['time']} ({draft['timezone']}), {draft['duration_minutes']} мин."
        return command_result(answer, created["why"], trace, created)
    except CalendarError as exc:
        record("google_calendar_error", "Проверяю ответ Google", {}, {"error": str(exc)})
        return command_result(str(exc), proof("Почему создание не подтверждено", "ошибка Google → сохранить запрос для безопасного повтора", {}, str(exc), "Google Calendar API"), trace, {"status": "error", "draft": draft})
