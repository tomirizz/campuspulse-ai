"""Session-scoped saved study notes; downloads include source provenance."""
from typing import Literal
import os

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from campuspulse.notebooks import build_notebook, export_notebook, notebook_metadata
from campuspulse.notebook_ai import enhance_notebook


class NotebookInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(default="", max_length=160)
    material_ids: list[str] = Field(min_length=1, max_length=10)
    focus: str = Field(default="", max_length=300)
    style: Literal["summary", "exam", "flashcards"] = "summary"

    @field_validator("material_ids")
    @classmethod
    def unique_ids(cls, value):
        if any(not isinstance(item, str) or not 1 <= len(item) <= 100 for item in value):
            raise ValueError("Проверьте идентификаторы материалов")
        return list(dict.fromkeys(value))


def register_notebooks(app, get_store, get_workspace):
    def get_note(sid, note_id):
        note = get_store().get(sid, "notebooks", note_id)
        if not note:
            raise HTTPException(404, "Конспект не найден в вашем пространстве")
        return note

    @app.get("/api/notebooks")
    def list_notes(request: Request):
        notes = get_store().list(request.state.sid, "notebooks")
        notes.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return {"notebooks": [notebook_metadata(note) for note in notes]}

    @app.post("/api/notebooks", status_code=201)
    async def create_note(body: NotebookInput, request: Request):
        store, sid = get_store(), request.state.sid
        if len(store.list(sid, "notebooks")) >= 50:
            raise HTTPException(400, "Можно сохранить до 50 конспектов; удалите ненужные")
        materials = []
        for material_id in body.material_ids:
            material = store.get(sid, "materials", material_id)
            if not material:
                raise HTTPException(404, "Один из выбранных материалов недоступен в вашем пространстве")
            materials.append(material)
        try:
            note = build_notebook(materials, title=body.title, focus=body.focus, style=body.style)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        if os.getenv("AGENT_MODE", "auto") != "tools" and (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_CLOUD_PROJECT")):
            note = await enhance_notebook(note, focus=body.focus)
        store.put(sid, "notebooks", note["id"], note)
        return note

    @app.get("/api/notebooks/{note_id}")
    def read_note(note_id: str, request: Request):
        return get_note(request.state.sid, note_id)

    @app.delete("/api/notebooks/{note_id}", status_code=204)
    def delete_note(note_id: str, request: Request):
        if not get_store().delete(request.state.sid, "notebooks", note_id):
            raise HTTPException(404, "Конспект не найден в вашем пространстве")

    @app.get("/api/notebooks/{note_id}/export")
    def download_note(note_id: str, request: Request, format: Literal["md", "txt", "html", "pdf"] = "md"):
        note = get_note(request.state.sid, note_id)
        try:
            payload, media_type = export_notebook(note, format)
        except ImportError as exc:
            raise HTTPException(503, "Для PDF установите reportlab. TXT, Markdown и HTML доступны") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return Response(payload, media_type=media_type, headers={
            "Content-Disposition": f'attachment; filename="campuspulse-notes-{note_id[:12]}.{format}"',
            "X-Content-Type-Options": "nosniff"})
