"""Persistent academic workspace, source import and grade-aware study planning."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
import uuid

from fastapi import Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from campuspulse.academic import AcademicSettings, CourseInput, analyze_course, academic_summary
from campuspulse.academic_import import EXAMPLE_SYLLABUS_TEXT, parse_syllabus, parse_schedule
from campuspulse.academic_planner import build_study_plan
from campuspulse.academic_ocr import extract_image
from campuspulse.academic_schedule import apply_exam_schedule
from campuspulse.academic_drafts import draft_courses
from campuspulse.syllabus_ai import extract_syllabus_ai
from campuspulse.models import TaskInput
from campuspulse.progress import proof


class ImportInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=60000)
    kind: str = "syllabus"
    year: int = Field(default=2026, ge=2020, le=2100)
    anchor_date: date | None = None
    weeks: int = Field(default=12, ge=1, le=20)


class ScoreInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: str = Field(min_length=1, max_length=100)
    score: float | None = Field(default=None, ge=0, allow_inf_nan=False)

class CourseMaterialsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    material_ids: list[str] = Field(max_length=10)


class ExamInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=160)
    course: str = Field(min_length=1, max_length=160)
    due_at: datetime
    assessment_kind: Literal["exam", "final", "midterm", "endterm"] = "exam"
    source_quote: str | None = Field(default=None, max_length=1000)

class WeeklyRuleInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    weekday: int = Field(ge=0, le=6)
    start_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end_time: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    title: str = Field(min_length=1, max_length=160)
    course: str = Field(default="", max_length=160)
    kind: str = Field(default="", max_length=80)
    room: str = Field(default="", max_length=160)
    source_quote: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def positive_time(self):
        if self.end_time <= self.start_time:
            raise ValueError("Конец еженедельного занятия должен быть позже начала")
        return self


class ScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    busy: list[dict] = Field(default_factory=list, max_length=500)
    exams: list[ExamInput] = Field(default_factory=list, max_length=200)
    recurring: bool = False
    weekly_rules: list[WeeklyRuleInput] = Field(default_factory=list, max_length=500)
    weekly_count: int | None = Field(default=None, ge=1, le=500)
    week_start: date | None = None
    coverage_end: date | None = None
    weeks: int | None = Field(default=None, ge=1, le=20)

    @model_validator(mode="after")
    def bounded_repetition(self):
        if self.recurring:
            if not self.weekly_rules or self.week_start is None or self.coverage_end is None or self.weeks is None:
                raise ValueError("Для еженедельного расписания нужны правила, начало и конец периода и число недель")
            if self.week_start.weekday() != 0 or self.coverage_end != self.week_start + timedelta(weeks=self.weeks, days=-1):
                raise ValueError("Проверьте понедельник начала и конец периода повторения расписания")
            if self.weekly_count is not None and self.weekly_count != len(self.weekly_rules):
                raise ValueError("Количество еженедельных занятий не совпадает со списком правил")
        return self


def academic_settings(store, sid):
    preferences = store.get(sid, "meta", "preferences") or {}
    hours = {k: preferences[k] for k in ("timezone", "daily_minutes", "start_hour", "end_hour") if k in preferences}
    return AcademicSettings.model_validate({**hours, **(store.get(sid, "meta", "academic_settings") or {})}).model_dump(mode="json")


def academic_context(store, sid, tasks=None):
    settings = academic_settings(store, sid)
    schedule = store.get(sid, "meta", "academic_schedule") or {"busy": [], "exams": []}
    saved_courses = store.list(sid, "courses")
    saved_by_id = {course["id"]: course for course in saved_courses}
    projections, notes = apply_exam_schedule(saved_courses, schedule)
    courses = []
    for projected in projections:
        links = projected.pop("_schedule_links", [])
        saved = saved_by_id[projected["id"]]
        derived_ids = {c["id"] for c in projected["components"] if c.get("due_at")
                       and not next((a.get("due_at") for a in saved["components"] if a["id"] == c["id"]), None)}
        courses.append({**analyze_course(projected, tasks=tasks or [], grade_scale=settings["grade_scale"],
                              min_target=settings["min_target"]), "schedule_links": links})
        for component in courses[-1]["components"]:
            component["schedule_derived"] = component["id"] in derived_ids
    courses.sort(key=lambda c: (-c["priority_score"], c["name"].casefold()))
    return {"courses": courses, "drafts": draft_courses(store, sid), "summary": academic_summary(courses), "settings": settings,
            "demo": store.get(sid, "meta", "academic_demo") or {"active": False},
            "imported_schedule": schedule, "schedule_notes": notes}


def academic_plan(context, tasks, preferences, now=None, days=7):
    settings = context["settings"]
    prefs = {**preferences, **{k: settings[k] for k in ("timezone", "daily_minutes", "start_hour", "end_hour")}}
    prefs["busy"] = [*preferences.get("busy", []), *settings.get("busy", [])]
    runtime = {**settings, "imported_busy": context.get("imported_schedule", {}).get("busy", [])}
    result = build_study_plan(context["courses"], tasks, prefs, runtime, now=now, days=days)
    result["schedule_notes"] = context.get("schedule_notes", [])
    result["why"] = proof("Как составлен учебный план", result["policy"],
        {"дневной лимит": settings["daily_minutes"], "окно": [settings["start_hour"], settings["end_hour"]], "расписание": context.get("imported_schedule", {})},
        result["scheduled_minutes"], "Оценки, кредиты, сложность, дедлайны и свободные интервалы", result["disclaimer"])
    for session in result["sessions"]:
        session["why"] = proof("Почему этот учебный блок", session["reason"],
            {"начало": session["start"], "конец": session["end"], "дедлайн": session.get("due_at")}, session["minutes"],
            "Подтверждённые предметы и занятые интервалы", result["disclaimer"])
    for risk in result["risks"]:
        risk["why"] = proof("Почему не хватает времени", "остаток = оценка длительности − выделенные минуты", dict(risk),
            risk.get("unscheduled_minutes", 0), "Свободные интервалы до дедлайна")
    return result


def register_academic(app, get_store, get_workspace, extract_material, sync_calendar=None):
    def checked(function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc

    def get_course(store, sid, course_id):
        course = store.get(sid, "courses", course_id)
        if not course:
            raise HTTPException(404, "Предмет не найден")
        return course

    def prepare_course(store, sid, body, course_id=None):
        value = body.model_dump(mode="json")
        if any(not store.get(sid, "materials", mid) for mid in value.get("material_ids", [])):
            raise HTTPException(422, "Один из учебных источников удалён или недоступен. Выберите материалы заново")
        value["id"] = course_id or uuid.uuid4().hex
        for component in value["components"]:
            component["id"] = component.get("id") or uuid.uuid4().hex
        ids = [c["id"] for c in value["components"]]
        if len(set(ids)) != len(ids):
            raise HTTPException(422, "Идентификаторы работ должны отличаться")
        # Validate the complete weighted model before storing any mutation.
        settings = academic_settings(store, sid)
        result = checked(analyze_course, value, grade_scale=settings["grade_scale"], min_target=settings["min_target"])
        return value, result

    def save_course(store, sid, body, course_id=None):
        value, result = prepare_course(store, sid, body, course_id)
        store.put(sid, "courses", value["id"], value)
        return result

    def patch_course(store, sid, course_id, change):
        def transform(value):
            # Read, patch and validate the latest persisted model under the
            # store's SQLite/Firestore transaction. A separate get -> put loses
            # concurrent changes to other assessments or material links.
            change(value)
            parsed = checked(CourseInput.model_validate, {k: v for k, v in value.items() if k != "id"})
            normalized, _ = prepare_course(store, sid, parsed, course_id)
            return normalized

        saved = store.update(sid, "courses", course_id, transform)
        if saved is None:
            raise HTTPException(404, "Предмет не найден")
        settings = academic_settings(store, sid)
        return checked(analyze_course, saved, grade_scale=settings["grade_scale"], min_target=settings["min_target"])

    @app.get("/api/academic")
    def read_academic(request: Request):
        data = get_workspace(request.state.sid)
        return checked(academic_context, get_store(), request.state.sid, data["tasks"])

    @app.post("/api/academic/courses", status_code=201)
    def create_course(body: CourseInput, request: Request):
        store, sid = get_store(), request.state.sid
        if len(store.list(sid, "courses")) >= 40:
            raise HTTPException(400, "Можно сохранить до 40 предметов")
        return save_course(store, sid, body)

    @app.put("/api/academic/courses/{course_id}")
    def edit_course(course_id: str, body: CourseInput, request: Request):
        get_course(get_store(), request.state.sid, course_id)
        return save_course(get_store(), request.state.sid, body, course_id)

    @app.patch("/api/academic/courses/{course_id}/scores")
    def update_score(course_id: str, body: ScoreInput, request: Request):
        store, sid = get_store(), request.state.sid

        def change(value):
            component = next((c for c in value["components"] if c["id"] == body.component_id), None)
            if not component:
                raise HTTPException(404, "Работа не найдена")
            component["score"] = body.score

        return patch_course(store, sid, course_id, change)

    @app.patch("/api/academic/courses/{course_id}/materials")
    def update_course_materials(course_id: str, body: CourseMaterialsInput, request: Request):
        store, sid = get_store(), request.state.sid
        return patch_course(store, sid, course_id, lambda value: value.update(material_ids=body.material_ids))

    @app.delete("/api/academic/courses/{course_id}", status_code=204)
    def delete_course(course_id: str, request: Request):
        if not get_store().delete(request.state.sid, "courses", course_id):
            raise HTTPException(404, "Предмет не найден")

    @app.put("/api/academic/settings")
    def update_settings(body: dict, request: Request):
        store, sid = get_store(), request.state.sid
        existing = academic_settings(store, sid)
        settings = checked(AcademicSettings.model_validate, {**existing, **body}).model_dump(mode="json")
        store.put(sid, "meta", "academic_settings", settings)
        prefs = get_workspace(sid)["preferences"]
        prefs.update({k: settings[k] for k in ("timezone", "daily_minutes", "start_hour", "end_hour")})
        store.put(sid, "meta", "preferences", prefs)
        return settings

    @app.get("/api/academic/plan")
    async def read_plan(request: Request, days: int = 7):
        if not 1 <= days <= 14:
            raise HTTPException(422, "Горизонт плана: от 1 до 14 дней")
        sid, store = request.state.sid, get_store()
        data = get_workspace(sid)
        from campuspulse.google_calendar import connection_status
        from campuspulse.features_api import with_calendar
        if sync_calendar and connection_status(store, sid)["connected"]:
            try:
                data["calendar_cache"] = await sync_calendar(store, sid, data["preferences"])
            except ValueError as exc:
                raise HTTPException(503, "Не удалось получить занятые часы Google Calendar. Обновите подключение") from exc
        from campuspulse.calendar_api import with_local_events
        data = with_local_events(with_calendar(data))
        context = checked(academic_context, store, sid, data["tasks"])
        return checked(academic_plan, context, data["tasks"], data["preferences"], days=days)

    def parse(text, kind, name, year, sid, anchor_date=None, weeks=12):
        if kind == "syllabus":
            return checked(parse_syllabus, text, name=name)
        if kind == "schedule":
            return checked(parse_schedule, text, year=year, timezone_name=academic_settings(get_store(), sid)["timezone"],
                           anchor_date=anchor_date, weeks=weeks)
        raise HTTPException(422, "Выберите силлабус или расписание")

    def remember_source(sid, name, pages, result):
        # One upload supplies both grading extraction and later study notes.
        store = get_store()
        existing = store.list(sid, "materials")
        material = next((m for m in existing if m["pages"] == pages), None)
        if not material:
            if len(existing) >= 10:
                result.setdefault("warnings", []).append("В библиотеке уже 10 источников. Схема прочитана, но для сохранения материала удалите ненужный файл.")
                return result
            material = {"id": uuid.uuid4().hex, "name": name[:160], "pages": pages, "page_count": len(pages),
                        "uploaded_at": datetime.now(timezone.utc).isoformat()}
            store.put(sid, "materials", material["id"], material)
        result["material_id"] = material["id"]
        if result.get("course"):
            result["course"]["material_ids"] = [material["id"]]
        return result

    @app.post("/api/academic/import")
    async def import_text(body: ImportInput, request: Request):
        result = parse(body.text, body.kind, "", body.year, request.state.sid, body.anchor_date, body.weeks)
        if body.kind == "syllabus":
            if result.get("confidence", 0) < .8:
                result = await extract_syllabus_ai(text=body.text) or result
            name = "Силлабус — " + result.get("course", {}).get("name", "предмет")
            result = remember_source(request.state.sid, name, [{"page": 1, "text": body.text}], result)
        return result

    @app.get("/api/academic/example")
    def example():
        return {**checked(parse_syllabus, EXAMPLE_SYLLABUS_TEXT), "is_example": True,
                "notice": "Пример из присланного силлабуса HPC. Оценки и даты не заданы; сохраните после проверки."}

    @app.post("/api/academic/import/file")
    async def import_file(request: Request, file: UploadFile, kind: str = Form("syllabus"), year: int = Form(2026),
                          anchor_date: date | None = Form(None), weeks: int = Form(12, ge=1, le=20)):
        if kind not in {"syllabus", "schedule"} or not 2020 <= year <= 2100:
            raise HTTPException(422, "Проверьте тип документа и год")
        name = Path(file.filename or "document.txt").name[:160]
        suffix = Path(name).suffix.lower()
        if suffix not in {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg"}:
            raise HTTPException(400, "Поддерживаются PDF, TXT, MD, PNG и JPG")
        raw = await file.read(5 * 1024 * 1024 + 1)
        await file.close()
        if len(raw) > 5 * 1024 * 1024:
            raise HTTPException(413, "Размер файла не должен превышать 5 МБ")
        try:
            extraction_error = None
            if suffix in {".png", ".jpg", ".jpeg"}:
                try:
                    extracted = await asyncio.to_thread(extract_image, raw, name)
                    pages = [{"page": 1, "text": extracted["text"]}]
                except ValueError as exc:
                    extraction_error = exc
                    pages, extracted = [], {"method": "Изображение"}
            else:
                try:
                    pages = await asyncio.to_thread(extract_material, raw, name)
                except ValueError as exc:
                    extraction_error = exc
                    pages = []
                extracted = {"method": "Текст PDF" if suffix == ".pdf" else "Текст файла"}
            text = "\n\n".join(p["text"] for p in pages)
            result = parse(text, kind, name, year, request.state.sid, anchor_date, weeks) if not extraction_error else None
            if kind == "syllabus" and (not result or result.get("confidence", 0) < .8):
                proposal = await extract_syllabus_ai(raw=raw if suffix in {".pdf", ".png", ".jpg", ".jpeg"} else None,
                                                   text=text, filename=name)
                if proposal:
                    result = proposal
                    if not pages:
                        pages = [{"page": 1, "text": proposal["source_text"]}]
                        result["warnings"].append("В библиотеке сохранены только распознанные фрагменты схемы, а не полный текст документа.")
            if not result:
                raise extraction_error or ValueError("Не удалось прочитать документ")
            if kind == "syllabus":
                result = remember_source(request.state.sid, name, pages, result)
            result.setdefault("extraction_method", extracted["method"])
            if extracted.get("warning"):
                result.setdefault("warnings", []).insert(0, extracted["warning"])
            return result
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, "Не удалось прочитать документ. Попробуйте вставить текст таблицы") from exc

    @app.post("/api/academic/schedule")
    def save_schedule(body: ScheduleInput, request: Request):
        cleaned = []
        for block in body.busy:
            try:
                start, end = datetime.fromisoformat(block["start"]), datetime.fromisoformat(block["end"])
                if start.tzinfo is None or end.tzinfo is None or end <= start:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as exc:
                raise HTTPException(422, "Проверьте даты и часовой пояс расписания") from exc
            cleaned.append({"start": start.isoformat(), "end": end.isoformat(), "title": str(block.get("title", "Занятие"))[:200]})
        # Exact imported instances only: an exam schedule never becomes weekly classes.
        for exam in body.exams:
            checked(TaskInput.aware_date, exam.due_at)
        value = {"busy": cleaned, "exams": [e.model_dump(mode="json") for e in body.exams], "saved_at": datetime.now(timezone.utc).isoformat()}
        if body.recurring:
            value.update(recurring=True, weekly_rules=[rule.model_dump() for rule in body.weekly_rules],
                         weekly_count=len(body.weekly_rules), week_start=body.week_start.isoformat(),
                         coverage_end=body.coverage_end.isoformat(), weeks=body.weeks)
        get_store().put(request.state.sid, "meta", "academic_schedule", value)
        return value
