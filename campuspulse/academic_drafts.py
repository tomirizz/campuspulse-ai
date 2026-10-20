"""Named course placeholders from a timetable, never invented grading schemes."""
from datetime import datetime, timezone
import hashlib
import threading

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator


_LOCK = threading.RLock()


def _name_key(name):
    return name.strip().casefold()


class DraftNamesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    names: list[str] = Field(min_length=1, max_length=40)

    @field_validator("names")
    @classmethod
    def checked_names(cls, value):
        if any(not 1 <= len(name.strip()) <= 160 for name in value):
            raise ValueError("Название предмета должно содержать от 1 до 160 символов")
        return [name.strip() for name in value]


def draft_courses(store, sid):
    """Return visible drafts; an existing real course always takes precedence."""
    existing = {_name_key(course["name"]) for course in store.list(sid, "courses")}
    return sorted((draft for draft in store.list(sid, "course_drafts")
                   if _name_key(draft["name"]) not in existing),
                  key=lambda draft: (draft["name"].casefold(), draft["id"]))


def add_course_drafts(store, sid, names):
    """Preflight the entire batch and keep repeated imports idempotent."""
    names = DraftNamesInput(names=names).names
    with _LOCK:
        real = store.list(sid, "courses")
        real_names = {_name_key(course["name"]) for course in real}
        visible = draft_courses(store, sid)
        known = {draft["id"] for draft in visible}
        requested = {}
        skipped = []
        for name in names:
            key = _name_key(name)
            if key in real_names:
                skipped.append(name)
            else:
                requested.setdefault(key, name)
        new = []
        stamp = datetime.now(timezone.utc).isoformat()
        for key, name in requested.items():
            identity = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
            if identity not in known:
                new.append({"id": identity, "name": name, "draft": True,
                            "needs_syllabus": True, "created_at": stamp})
        if len(real) + len(visible) + len(new) > 40:
            raise ValueError("Можно сохранить до 40 предметов вместе с черновиками. Удалите ненужные или выберите меньше новых предметов")
        for draft in new:
            store.put_once(sid, "course_drafts", draft["id"], draft)
        return {"drafts": draft_courses(store, sid), "created_count": len(new),
                "skipped_existing": list(dict.fromkeys(skipped))}


def register_academic_drafts(app, get_store):
    @app.get("/api/academic/course-drafts")
    def read_drafts(request: Request):
        return {"drafts": draft_courses(get_store(), request.state.sid)}

    @app.post("/api/academic/course-drafts")
    def create_drafts(body: DraftNamesInput, request: Request):
        try:
            return add_course_drafts(get_store(), request.state.sid, body.names)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.delete("/api/academic/course-drafts/{draft_id}", status_code=204)
    def remove_draft(draft_id: str, request: Request):
        if not get_store().delete(request.state.sid, "course_drafts", draft_id):
            raise HTTPException(404, "Черновик предмета не найден")
