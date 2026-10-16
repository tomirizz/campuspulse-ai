"""Deterministic scheduling; the model cannot invent available time."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from campuspulse.models import Preferences
from campuspulse.progress import proof


def plan_week(tasks: list[dict], preferences: dict | None = None,
              now: datetime | None = None, days: int = 7) -> dict:
    prefs = Preferences.model_validate(preferences or {})
    if prefs.end_hour <= prefs.start_hour:
        raise ValueError("Конец учебного окна должен быть позже начала")
    if any(b.end <= b.start for b in prefs.busy):
        raise ValueError("Конец занятого интервала должен быть позже начала")
    tz = ZoneInfo(prefs.timezone)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    open_tasks = [t for t in tasks if not t.get("completed")]
    ordered = sorted(open_tasks, key=lambda t: (
        datetime.fromisoformat(t["due_at"]), 0 if t.get("priority") == "high" else 1))
    slots = []
    # Quantized 15-minute slots; never schedule before now or past a deadline.
    for day in range(min(max(days, 1), 14)):
        base = (now + timedelta(days=day)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = base + timedelta(hours=prefs.start_hour)
        end = base + timedelta(hours=prefs.end_hour)
        while start + timedelta(minutes=15) <= end:
            stop = start + timedelta(minutes=15)
            if start >= now and not any(start < b.end and stop > b.start for b in prefs.busy):
                slots.append((start, stop))
            start = stop
    used: set[int] = set()
    spent: dict[str, int] = {}
    sessions, risks = [], []
    for task in ordered:
        due = datetime.fromisoformat(task["due_at"]).astimezone(tz)
        remaining = task["estimated_minutes"]
        if due <= now:
            risks.append({"task_id": task["id"], "title": task["title"],
                          "reason": "Дедлайн прошёл", "unscheduled_minutes": remaining})
            continue
        for i, (start, end) in enumerate(slots):
            day_key = start.date().isoformat()
            if not remaining:
                break
            if i in used or end > due or spent.get(day_key, 0) + 15 > prefs.daily_minutes:
                continue
            amount = min(15, remaining)
            finish = start + timedelta(minutes=amount)
            if (sessions and sessions[-1]["task_id"] == task["id"]
                    and sessions[-1]["end"] == start.isoformat()
                    and sessions[-1]["minutes"] + amount <= 60):
                sessions[-1]["end"] = finish.isoformat()
                sessions[-1]["minutes"] += amount
            else:
                sessions.append({"task_id": task["id"], "title": task["title"],
                                 "course": task["course"], "start": start.isoformat(),
                                 "end": finish.isoformat(), "minutes": amount})
            used.add(i)
            spent[day_key] = spent.get(day_key, 0) + amount
            remaining -= amount
        if remaining:
            risks.append({"task_id": task["id"], "title": task["title"],
                          "reason": "Не хватает свободного времени до дедлайна в горизонте плана",
                          "unscheduled_minutes": remaining})
    for session in sessions:
        session["why"] = proof("Почему этот блок", "минуты = (конец − начало) / 60 секунд; ближайший дедлайн первым",
            {"task_id": session["task_id"], "start": session["start"], "end": session["end"], "daily_limit": prefs.daily_minutes}, session["minutes"],
            "Ваши задания + настройки времени → campuspulse/planner.py → plan_week", "Шаг сетки 15 минут, длина блока до 60 минут; занятые интервалы исключены.")
    for risk in risks:
        task = next(t for t in tasks if t["id"] == risk["task_id"])
        allocated = sum(s["minutes"] for s in sessions if s["task_id"] == task["id"])
        risk["why"] = proof("Почему не помещается", "остаток = оценка минут − запланированные минуты",
            {"оценка": task["estimated_minutes"], "запланировано": allocated, "дедлайн": task["due_at"], "сейчас": now.isoformat()},
            risk["unscheduled_minutes"], "Ваше задание + свободные интервалы", "Жадный алгоритм по ближайшему дедлайну; это не доказательство глобально оптимального расписания.")
    return {"sessions": sorted(sessions, key=lambda s: s["start"]), "risks": risks,
            "why": proof("Как рассчитан план", "запланированные минуты = сумма длительностей блоков",
                         {"блоки": [s["minutes"] for s in sessions], "дневной лимит": prefs.daily_minutes, "часовой пояс": prefs.timezone,
                          "учебное окно": [prefs.start_hour, prefs.end_hour], "занятые интервалы": [b.model_dump(mode="json") for b in prefs.busy]},
                         sum(s["minutes"] for s in sessions), "campuspulse/planner.py → plan_week", "План рассчитывается кодом. Модель не изменяет минуты, порядок или формулу."),
            "scheduled_minutes": sum(s["minutes"] for s in sessions),
            "timezone": prefs.timezone, "generated_at": now.isoformat(),
            "policy": "Сначала ближайший дедлайн; при равенстве — высокий приоритет. Блоки до 60 минут."}


def calendar_export(plan: dict) -> str:
    def escape(value):
        return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;").replace("\r", "")
    def stamp(value):
        return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//CampusPulse//Study Plan//RU", "CALSCALE:GREGORIAN"]
    for session in plan["sessions"]:
        lines.extend(["BEGIN:VEVENT", f"UID:{session['task_id']}-{stamp(session['start'])}@campuspulse",
                      f"DTSTAMP:{stamp(plan['generated_at'])}", f"DTSTART:{stamp(session['start'])}",
                      f"DTEND:{stamp(session['end'])}", f"SUMMARY:{escape(session['title'])}",
                      f"DESCRIPTION:{escape(session['course'])}", "END:VEVENT"])
    lines.append("END:VCALENDAR")
    # RFC 5545: fold at 75 OCTETS, keeping UTF-8 characters intact.
    folded = []
    for line in lines:
        current = ""
        for char in line:
            if len((current + char).encode()) > 75:
                folded.append(current)
                current = " "
            current += char
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"
