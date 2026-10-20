"""Study-time allocation from observed tasks, course risk and actual free time."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from types import SimpleNamespace
from zoneinfo import ZoneInfo


def _aware(value, zone):
    if isinstance(value, datetime):
        date = value
    else:
        date = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if date.tzinfo is None or date.utcoffset() is None:
        raise ValueError("Дата должна содержать часовой пояс")
    return date.astimezone(zone)


def _number(value, default, low, high):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number)) if math.isfinite(number) else default


def _ceil_grid(value):
    result = value.replace(second=0, microsecond=0)
    if result < value:
        result += timedelta(minutes=1)
    if result.minute % 15:
        result += timedelta(minutes=15 - result.minute % 15)
    return result


def _free_intervals(start, end, busy):
    free = [(start, end)]
    for blocked_start, blocked_end in busy:
        next_free = []
        for left, right in free:
            if blocked_end <= left or blocked_start >= right:
                next_free.append((left, right))
            else:
                if left < blocked_start:
                    next_free.append((left, blocked_start))
                if blocked_end < right:
                    next_free.append((blocked_end, right))
        free = next_free
    return free


def build_study_plan(courses: list[dict], tasks: list[dict], preferences: dict | None,
                     settings: dict | None = None, now: datetime | None = None,
                     days: int = 7) -> dict:
    """Allocate bounded sessions with weighted fairness and deadline urgency.

    Minutes estimate preparation effort only; they are not a prediction or a
    guarantee of a particular grade. Existing task and course estimates are used
    before conservative, editable defaults for remaining assessments.
    """
    settings = settings or {}
    if hasattr(preferences, "model_dump"):
        preferences = preferences.model_dump(mode="json")
    supplied_prefs = preferences or {}
    prefs = SimpleNamespace(timezone=str(supplied_prefs.get("timezone") or "Asia/Almaty"),
        daily_minutes=int(_number(supplied_prefs.get("daily_minutes"), 180, 15, 600)),
        start_hour=int(_number(supplied_prefs.get("start_hour"), 16, 0, 23)),
        end_hour=int(_number(supplied_prefs.get("end_hour"), 22, 1, 24)),
        busy=list(supplied_prefs.get("busy") or []))
    if prefs.end_hour <= prefs.start_hour:
        raise ValueError("Конец учебного окна должен быть позже начала")
    zone = ZoneInfo(prefs.timezone)
    now = _aware(now or datetime.now(timezone.utc), zone)
    days = min(14, max(1, int(days)))
    max_session = int(_number(settings.get("session_minutes"), 50, 15, 60))
    break_minutes = int(_number(settings.get("break_minutes"), 10, 5, 30))
    busy = []
    risks = []
    extra_busy = list(settings.get("busy") or []) + list(settings.get("imported_busy") or [])
    for block in prefs.busy + extra_busy:
        try:
            if hasattr(block, "model_dump"):
                block = block.model_dump(mode="json")
            start, end = _aware(block["start"], zone), _aware(block["end"], zone)
            if end <= start:
                raise ValueError("Конец занятого интервала раньше начала")
            busy.append((start, end))
        except (KeyError, TypeError, ValueError):
            risks.append({"reason": "Некорректный занятый интервал пропущен; проверьте настройки времени.", "unscheduled_minutes": 0})
    # Merge overlaps and duplicate imports so daily busy totals stay honest.
    merged_busy = []
    for start, end in sorted(busy):
        if merged_busy and start <= merged_busy[-1][1]:
            merged_busy[-1] = merged_busy[-1][0], max(end, merged_busy[-1][1])
        else:
            merged_busy.append((start, end))
    busy = merged_busy
    horizon_end = (now + timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=prefs.end_hour)
    course_map = {}
    course_names = {}
    risk_factors = {"critical": 2.8, "high": 2.2, "medium": 1.6, "low": 1.0, "ungraded": 1.25, "complete": 0}
    for index, raw in enumerate(courses[:100]):
        course = raw.get("course", raw)
        name = str(course.get("name") or f"Предмет {index + 1}")
        components = course.get("components") or []
        complete = all(c.get("score") is not None for c in components) if components else course.get("remaining_weight") == 0
        difficulty = _number(course.get("difficulty"), 3, 1, 5)
        credits = _number(course.get("credits"), 5, .1, 60)
        risk = course.get("risk", "ungraded")
        factor = risk_factors.get(risk, 1.25)
        reasons = list(course.get("priority_reasons") or [])
        if not reasons:
            reasons = [f"Кредиты: {credits:g}; сложность: {difficulty:g}/5; риск: {risk}."]
        identity = str(course.get("id") or f"course-{index + 1}")
        course_map[identity] = {"name": name, "id": identity,
            "credits": credits, "difficulty": difficulty, "risk": risk,
            "weight": 0 if complete else credits * difficulty * factor,
            "priority_score": course.get("priority_score", credits * difficulty * factor),
            "reasons": reasons, "spent": 0, "demand": 0, "complete": complete, "raw": course}
        course_names.setdefault(name.strip().casefold(), []).append(identity)

    items = []
    explicit_keys = set()

    def add_item(raw, entry, synthetic=False):
        if raw.get("completed") or entry["complete"]:
            return
        title = str(raw.get("title") or raw.get("name") or "Подготовка к занятию")[:160]
        identity = str(raw.get("id") or f"study-{entry['id']}-{len(items) + 1}")
        if synthetic:
            identity = f"academic-{entry['id']}-{identity}"
        estimate = int(_number(raw.get("estimated_minutes"), 120 if synthetic else 60, 1, 2400))
        try:
            due = _aware(raw["due_at"], zone) if raw.get("due_at") else horizon_end
        except (ValueError, TypeError):
            risks.append({"task_id": identity, "title": title, "course": entry["name"],
                          "reason": "Не удалось прочитать дедлайн; время не назначено.", "unscheduled_minutes": estimate})
            return
        entry["demand"] += estimate
        if due <= now:
            risks.append({"task_id": identity, "title": title, "course": entry["name"],
                          "reason": "Дедлайн прошёл; укажите новую дату.", "unscheduled_minutes": estimate})
            return
        items.append({"id": identity, "title": title, "entry": entry, "due": due,
                      "remaining": estimate, "estimate": estimate,
                      "has_deadline": bool(raw.get("due_at")),
                      "high": raw.get("priority") == "high", "synthetic": synthetic})

    for task in tasks[:1000]:
        name = str(task.get("course") or "Другие задания")
        matching = course_names.get(name.strip().casefold(), [])
        explicit_course = task.get("course_id")
        if explicit_course in course_map:
            key = explicit_course
        elif len(matching) == 1:
            key = matching[0]
        elif len(matching) > 1:
            if not task.get("completed"):
                risks.append({"task_id": str(task.get("id", "")), "title": str(task.get("title", "Задание")),
                    "course": name, "reason": "Несколько предметов имеют такое название. Уточните предмет задания; до этого оно не привязано автоматически. Работы каждого предмета планируются отдельно.",
                    "unscheduled_minutes": int(_number(task.get("estimated_minutes"), 60, 1, 2400))})
            continue
        else:
            key = "task-course-" + str(len(course_map) + 1)
            while key in course_map:
                key += "-task"
            course_map[key] = {"name": name, "id": key, "credits": 5,
                "difficulty": 3, "risk": "ungraded", "weight": 18.75, "priority_score": 18.75,
                "reasons": ["Предмет без оценочной схемы: используются редактируемые базовые настройки."],
                "spent": 0, "demand": 0, "complete": False, "raw": {}}
            course_names.setdefault(name.strip().casefold(), []).append(key)
        add_item(task, course_map[key])
        explicit_keys.add((key, str(task.get("title", "")).strip().casefold()))
        if task.get("assessment_id"):
            explicit_keys.add((key, str(task["assessment_id"])))
    for key, entry in course_map.items():
        if entry["complete"]:
            continue
        components = entry["raw"].get("components") or []
        for component in components:
            if component.get("score") is not None:
                continue
            if ((key, str(component.get("name", "")).strip().casefold()) in explicit_keys
                    or (key, str(component.get("id", ""))) in explicit_keys):
                continue
            add_item({**component, "title": component.get("name", "Подготовка")}, entry, synthetic=True)
        if not components and not any(i["entry"] is entry for i in items) and entry["raw"]:
            # A course without a scheme still gets an explicit, editable practice estimate.
            add_item({"title": "Самостоятельная работа", "estimated_minutes": 120}, entry, synthetic=True)

    sessions, day_rows = [], []
    for offset in range(days):
        day = (now + timedelta(days=offset)).replace(hour=0, minute=0, second=0, microsecond=0)
        window_start, window_end = day + timedelta(hours=prefs.start_hour), day + timedelta(hours=prefs.end_hour)
        available_start = max(window_start, now)
        intervals = _free_intervals(available_start, window_end, busy) if available_start < window_end else []
        free_minutes = sum(int((end - start).total_seconds() // 60) for start, end in intervals)
        day_spent = 0
        day_sessions = []
        for left, right in intervals:
            cursor = _ceil_grid(left)
            while cursor < right and day_spent < prefs.daily_minutes:
                available = [item for item in items if item["remaining"] > 0 and item["due"] > cursor]
                # First select the nearest pending assessment in each course.
                per_course = {}
                for item in sorted(available, key=lambda i: (i["due"], not i["high"], i["id"])):
                    per_course.setdefault(item["entry"]["id"], item)
                candidates = list(per_course.values())
                if not candidates:
                    break

                def urgency(item):
                    hours = (item["due"] - cursor).total_seconds() / 3600
                    boost = 4 if hours <= 24 else 2.5 if hours <= 48 else 1.5 if hours <= 96 else 1
                    return item["entry"]["weight"] * boost * (1.25 if item["high"] else 1) / (item["entry"]["spent"] + max_session)

                candidates.sort(key=lambda i: (
                    0 if (i["due"] - cursor).total_seconds() <= 7200 else 1,
                    i["due"] if (i["due"] - cursor).total_seconds() <= 7200 else horizon_end,
                    0 if i["entry"]["spent"] == 0 else 1,
                    -urgency(i), i["due"], i["id"]))
                chosen = None
                for item in candidates:
                    possible = int((min(right, item["due"]) - cursor).total_seconds() // 60)
                    daily_left = prefs.daily_minutes - day_spent
                    amount = min(max_session, item["remaining"], daily_left, possible)
                    # Split 55min as 28+27, not 50+5, provided the next
                    # portion can still fit. A hard imminent deadline wins.
                    minimum = min(25, max_session)
                    enough_room = (possible >= item["remaining"] + break_minutes + 14
                                   or (item["due"] - cursor).total_seconds() >= 3 * 3600)
                    tail = item["remaining"] - amount
                    if 0 < tail < minimum and item["remaining"] >= 2 * minimum and enough_room:
                        amount = min(amount, math.ceil(item["remaining"] / 2))
                    # Leave a useful final block within the daily budget.
                    # Work estimates and the configured cap remain exact.
                    daily_tail = daily_left - amount
                    if 0 < daily_tail < minimum and daily_left >= 2 * minimum:
                        balanced_amount = min(amount, daily_left - minimum)
                        item_tail = item["remaining"] - balanced_amount
                        if item_tail == 0 or item_tail >= 15:
                            amount = balanced_amount
                    # Never leave an unplaceable <15min fragment that would
                    # obstruct subsequent assessments in the same course.
                    item_tail = item["remaining"] - amount
                    if 0 < item_tail < 15:
                        if item["remaining"] < 30:
                            # A 23min task needs a whole usable window, not
                            # 15min today followed by an orphan 8min tomorrow.
                            continue
                        amount = min(amount, item["remaining"] - 15)
                    if amount >= 15:
                        chosen = item, amount
                        break
                if chosen is None:
                    break
                item, amount = chosen
                finish = cursor + timedelta(minutes=amount)
                entry = item["entry"]
                session = {"task_id": item["id"], "title": item["title"], "course": entry["name"], "course_id": entry["id"],
                    "start": cursor.isoformat(), "end": finish.isoformat(), "minutes": amount,
                    "kind": "preparation" if item["synthetic"] else "task",
                    "due_at": item["due"].isoformat() if item["has_deadline"] else None,
                    "reason": f"Кредиты {entry['credits']:g} × сложность {entry['difficulty']:g}/5; риск {entry['risk']}; ближе дедлайн — выше приоритет."
                              + (" Короткий блок: остаток задания или доступного времени." if amount < 25 else "")}
                sessions.append(session)
                day_sessions.append(session)
                item["remaining"] -= amount
                entry["spent"] += amount
                day_spent += amount
                cursor = _ceil_grid(finish + timedelta(minutes=break_minutes))
        day_busy = []
        for start, end in busy:
            if start < day + timedelta(days=1) and end > day:
                day_busy.append({"start": max(start, day).isoformat(), "end": min(end, day + timedelta(days=1)).isoformat()})
        day_rows.append({"date": day.date().isoformat(), "free_minutes": free_minutes,
                         "available_minutes": min(free_minutes, prefs.daily_minutes), "scheduled_minutes": day_spent,
                         "busy": day_busy, "sessions": day_sessions,
                         "window_start": window_start.isoformat(), "window_end": window_end.isoformat()})
    for item in items:
        if item["remaining"]:
            risks.append({"task_id": item["id"], "title": item["title"], "course": item["entry"]["name"],
                          "reason": "Не хватает свободного времени до дедлайна в выбранном горизонте." if item["has_deadline"] else "Не хватает свободного времени в выбранном горизонте плана.",
                          "unscheduled_minutes": item["remaining"]})
    total = sum(s["minutes"] for s in sessions)
    allocations = [{"course": entry["name"], "course_id": entry["id"], "minutes": entry["spent"],
        "scheduled_minutes": entry["spent"], "required_minutes": entry["demand"],
        "unscheduled_minutes": entry["demand"] - entry["spent"],
        "share_percent": round(entry["spent"] / total * 100, 1) if total else 0,
        "priority_score": entry["priority_score"], "weight": round(entry["weight"], 3),
        "credits": entry["credits"], "difficulty": entry["difficulty"], "risk": entry["risk"],
        "reasons": entry["reasons"]} for entry in course_map.values()]
    allocations.sort(key=lambda a: (-a["minutes"], -float(a["priority_score"] or 0), a["course"]))
    return {"sessions": sessions, "risks": risks, "course_allocations": allocations, "days": day_rows,
            "scheduled_minutes": total, "timezone": prefs.timezone, "generated_at": now.isoformat(),
            "defaults": {"daily_minutes": prefs.daily_minutes, "start_hour": prefs.start_hour,
                         "end_hour": prefs.end_hour, "session_minutes": max_session, "break_minutes": break_minutes,
                         "difficulty": 3, "assessment_minutes": 120},
            "policy": "Свободное время распределяется по кредитам, сложности, риску и близости дедлайна. Блоки обычно 25–50 минут, минимум 15; после блока — перерыв. Завершённые предметы исключены.",
            "disclaimer": "Время — оценка подготовки, а не гарантия балла. Настройки, сложность и длительность задач можно изменить."}
