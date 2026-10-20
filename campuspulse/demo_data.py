"""Explicit, removable demo workspace. Startup never seeds student data."""
from datetime import datetime, timedelta, timezone
import threading
import uuid
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

from campuspulse.academic import CourseInput
from campuspulse.notebooks import build_notebook


_LOCK = threading.RLock()
_KINDS = {"course_ids": "courses", "material_ids": "materials",
          "local_event_ids": "local_events", "notebook_ids": "notebooks"}
NOTICE = "Учебный пример: вымышленные оценки, материалы и занятия. Это не ваши реальные данные. Пример можно удалить одной кнопкой."


def _id():
    return uuid.uuid4().hex


def _build_records(now, zone):
    local_now = now.astimezone(zone)
    stamp = now.isoformat()
    records = []
    material_ids = [_id(), _id()]
    materials = [
        {"id": material_ids[0], "name": "HPC — учебный конспект · пример.txt", "page_count": 1,
         "uploaded_at": stamp, "demo_notice": NOTICE, "pages": [{"page": 1, "text": (
             "Параллелизм: одновременное выполнение нескольких вычислительных задач.\n"
             "Ускорение: отношение времени последовательного выполнения к времени параллельного выполнения.\n"
             "Синхронизация: согласование действий параллельно работающих задач.\n"
             "Независимые задачи: задачи, которые могут выполняться без ожидания результатов друг друга.\n"
             "Общая память: область памяти, доступная нескольким выполняющимся задачам.\n"
             "Распределение данных: разделение набора данных на части для обработки разными задачами.\n"
         )}]},
        {"id": material_ids[1], "name": "Statistics — учебный конспект · пример.txt", "page_count": 1,
         "uploaded_at": stamp, "demo_notice": NOTICE, "pages": [{"page": 1, "text": (
             "Среднее арифметическое: сумма значений, делённая на их количество.\n"
             "Медиана: центральное значение упорядоченного набора данных, а для чётного числа значений среднее двух центральных.\n"
             "Выборка: набор наблюдений, используемый для анализа.\n"
             "Мода: значение, которое встречается в наборе данных чаще всего.\n"
             "Размах: разность между максимальным и минимальным значением набора данных.\n"
             "Для набора 2, 4 и 6 среднее арифметическое равно 4.\n"
         )}]},
    ]
    records.extend(("materials", material["id"], material) for material in materials)

    def assessment(name, weight, score=None, due_days=None, minutes=120):
        due = (local_now + timedelta(days=due_days)).replace(hour=20, minute=0, second=0, microsecond=0) if due_days else None
        return {"id": _id(), "name": name, "weight": weight, "score": score, "max_score": 100,
                "estimated_minutes": minutes, "due_at": due.isoformat() if due else None,
                "source_quote": "Учебный пример CampusPulse. Веса и даты этой демонстрации нужно заменить своим силлабусом."}

    definitions = [
        ("High Performance Computing (HPC) · пример", 5, 5, [material_ids[0]], [
            assessment("Assignment 1", 12, 75), assessment("Midterm", 18, 80),
            assessment("Assignment 2", 6, due_days=4, minutes=180),
            assessment("Assignment 3", 6, due_days=9, minutes=180),
            assessment("Endterm", 18, due_days=12, minutes=240),
            assessment("Final exam", 40, due_days=21, minutes=360),
        ]),
        ("Computational Mathematics · пример", 5, 4, [], [
            assessment("Homework", 20, 94), assessment("Quiz", 20, 96),
            assessment("Project", 20, due_days=7, minutes=180),
            assessment("Final exam", 40, due_days=18, minutes=240),
        ]),
        ("Academic Writing · пример", 3, 2, [], [
            assessment("Essay draft", 25, 87), assessment("Presentation", 25, 90),
            assessment("Final essay", 50, due_days=10, minutes=180),
        ]),
        ("Statistics and Data Science · пример", 5, 4, [material_ids[1]], [
            assessment("Quiz", 15, 48), assessment("Assignment", 15, 56), assessment("Midterm", 30, 60),
            assessment("Project", 20, due_days=3, minutes=180),
            assessment("Final exam", 20, due_days=11, minutes=240),
        ]),
    ]
    courses = []
    for name, credits, difficulty, links, components in definitions:
        raw = {"name": name, "credits": credits, "difficulty": difficulty, "target": 95,
               "term": "trimester", "components": components}
        if "material_ids" in CourseInput.model_fields:
            raw["material_ids"] = links
        value = CourseInput.model_validate(raw).model_dump(mode="json")
        value["id"] = _id()
        courses.append(value)
        records.append(("courses", value["id"], value))

    notes = [build_notebook([material], title=("HPC" if index == 0 else "Statistics") + " · пример",
                            style="exam", now=now) for index, material in enumerate(materials)]
    records.extend(("notebooks", note["id"], note) for note in notes)

    # Two actual dated occurrences per weekly class. They never become a user's
    # imported academic_schedule and never overwrite availability preferences.
    schedule = [(0, 10, 90, 1), (1, 16, 60, 0), (2, 14, 90, 3),
                (3, 11, 60, 2), (4, 17, 60, 0), (4, 9, 60, 1)]
    local_events = []
    for weekday, hour, duration, index in schedule:
        start = (local_now + timedelta(days=(weekday - local_now.weekday()) % 7)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if start <= local_now:
            start += timedelta(days=7)
        series_id = _id()
        for week in range(2):
            beginning = start + timedelta(weeks=week)
            event = {"id": _id(), "title": courses[index]["name"] + " — занятие",
                     "start": beginning.isoformat(), "end": (beginning + timedelta(minutes=duration)).isoformat(),
                     "category": "class", "description": NOTICE, "busy": True, "kind": "local",
                     "editable": True, "google_status": "local", "series_id": series_id, "created_at": stamp}
            local_events.append(event)
            records.append(("local_events", event["id"], event))
    meta = {"active": True, "course_ids": [c["id"] for c in courses], "material_ids": material_ids,
            "local_event_ids": [event["id"] for event in local_events], "notebook_ids": [note["id"] for note in notes],
            "created_at": stamp, "notice": NOTICE}
    return records, meta


def create_demo(store, sid, now=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Дата примера должна включать часовой пояс")
    with _LOCK:
        previous = store.get(sid, "meta", "academic_demo")
        if previous and previous.get("active"):
            return {**previous, "status": "already"}
        settings = store.get(sid, "meta", "academic_settings") or {}
        preferences = store.get(sid, "meta", "preferences") or {}
        zone = ZoneInfo(settings.get("timezone") or preferences.get("timezone") or "Asia/Almaty")
        records, meta = _build_records(now, zone)
        additions = {kind: sum(item[0] == kind for item in records) for kind in _KINDS.values()}
        limits = {"courses": 40, "materials": 10, "local_events": 1000, "notebooks": 50}
        for kind, count in additions.items():
            if len(store.list(sid, kind)) + count > limits[kind]:
                raise ValueError(f"Недостаточно места для учебного примера: {kind}, лимит {limits[kind]}. Удалите ненужные записи или продолжайте со своими данными.")
        written = []
        try:
            for kind, key, value in records:
                written.append((kind, key))
                store.put(sid, kind, key, value)
            store.put(sid, "meta", "academic_demo", meta)
        except Exception:
            for kind, key in reversed(written):
                store.delete(sid, kind, key)
            if previous is None:
                store.delete(sid, "meta", "academic_demo")
            else:
                store.put(sid, "meta", "academic_demo", previous)
            raise
        return {**meta, "status": "created"}


def _material_references(value):
    """Collect explicit source IDs, including nested task/quest citations."""
    references, pending = set(), [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if isinstance(item.get("material_id"), str):
                references.add(item["material_id"])
            ids = item.get("material_ids")
            if isinstance(ids, list):
                references.update(mid for mid in ids if isinstance(mid, str))
            pending.extend(child for child in item.values() if isinstance(child, (dict, list)))
        elif isinstance(item, list):
            pending.extend(child for child in item if isinstance(child, (dict, list)))
    return references


def delete_demo(store, sid):
    with _LOCK:
        meta = store.get(sid, "meta", "academic_demo") or {}
        seed_ids = {kind: {key for key in meta.get(field, []) if isinstance(key, str)}
                    for field, kind in _KINDS.items()}
        used_materials = set()
        # A user may deliberately reuse a demo source in personal work. Keep
        # that labelled source rather than breaking the surviving record or
        # silently removing its provenance. Seed records being deleted do not
        # count as surviving references.
        for kind in ("courses", "notebooks", "tasks", "quests", "quest_rewards"):
            for record in store.list(sid, kind):
                if record.get("id") not in seed_ids.get(kind, set()):
                    used_materials.update(_material_references(record))
        used_materials.update(_material_references(store.get(sid, "meta", "grade_config")))
        preserved = sorted(mid for mid in seed_ids["materials"] & used_materials
                           if store.get(sid, "materials", mid) is not None)
        removed = {}
        for field, kind in _KINDS.items():
            # Only IDs recorded at explicit demo creation are ever touched.
            removed[kind] = sum(bool(store.delete(sid, kind, key)) for key in meta.get(field, [])
                                if isinstance(key, str) and not (kind == "materials" and key in preserved))
        store.delete(sid, "meta", "academic_demo")
        result = {"active": False, "status": "removed", "removed": removed,
                  "preserved": {"materials": len(preserved)}, "preserved_material_ids": preserved}
        if preserved:
            result["notice"] = (f"Пример удалён. Сохранено учебных источников: {len(preserved)}, "
                                "потому что они используются в ваших личных предметах, конспектах или заданиях. "
                                "Их пометка «пример» сохранена; личные данные и ссылки не изменены.")
        return result


def register_demo(app, get_store):
    @app.post("/api/academic/demo")
    def add_demo(request: Request):
        try:
            return create_demo(get_store(), request.state.sid)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/academic/demo")
    def remove_demo(request: Request):
        return delete_demo(get_store(), request.state.sid)
