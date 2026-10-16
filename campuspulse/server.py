import asyncio
from datetime import datetime, timezone
from io import BytesIO
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader

from campuspulse.agent import gemini_run, tools_only_run
from campuspulse.models import ChatInput, Preferences, TaskInput, TaskPatch
from campuspulse.planner import calendar_export, plan_week
from campuspulse.storage import make_store
from campuspulse.tools import ToolHub
from campuspulse.calendar_dialogue import calendar_dialogue
from campuspulse.google_calendar import connection_status
from campuspulse.features_api import register_features, sync_calendar, with_calendar
from campuspulse.study import validate_source, scenario_from_message
from campuspulse.progress import progress, metrics, task_proof, complete_task, proof
from fastapi.exceptions import RequestValidationError

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="CampusPulse AI", version="0.3.0", docs_url="/api/docs")
store = make_store()
chat_slots = asyncio.Semaphore(4)
active_sessions: set[str] = set()


@app.middleware("http")
async def session_boundary(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin:
        if urlsplit(origin).netloc != request.url.netloc:
            return JSONResponse({"detail": "Запрос с другого сайта запрещён"}, status_code=403)
    sid = request.cookies.get("campuspulse_session", "")
    new_session = not re.fullmatch(r"[0-9a-f]{64}", sid)
    if new_session:
        sid = secrets.token_hex(32)
    request.state.sid = sid
    response = await call_next(request)
    if new_session:
        response.set_cookie("campuspulse_session", sid, httponly=True,
                            secure=os.getenv("COOKIE_SECURE", "false").lower() == "true",
                            samesite="lax", max_age=60 * 60 * 24 * 30)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; img-src 'self' data:; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    else:
        response.headers["Cache-Control"] = "no-cache"
    return response


def workspace(sid):
    return {"tasks": store.list(sid, "tasks"), "materials": store.list(sid, "materials"),
            "preferences": {**Preferences().model_dump(mode="json"), **(store.get(sid, "meta", "preferences") or {})},
            "quest_rewards": store.list(sid, "quest_rewards"),
            **{key: store.get(sid, "meta", key) for key in ("grade_config", "diagnostic", "scenario_input", "calendar_cache", "calendar_draft", "google_notice")}}


def effective_mode():
    mode = os.getenv("AGENT_MODE", "auto")
    if mode in {"auto", "local"}:
        if os.getenv("ENGINE_RESOURCE_NAME"):
            return "remote"
        if os.getenv("GOOGLE_CLOUD_PROJECT"):
            try:
                import google.auth
                google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
                return "gemini"
            except Exception:
                pass
        return "tools"
    return mode


@app.get("/api/health")
async def health():
    mode = effective_mode()
    return {"ok": True, "version": "0.3.0", "mode": mode,
            "model": os.getenv("GEMINI_MODEL", "gemini-3.6-flash") if mode != "tools" else None,
            "storage": os.getenv("STORAGE_BACKEND", "sqlite"),
            "cloud_configured": bool(os.getenv("ENGINE_RESOURCE_NAME")),
            "cloud_verified": False,
            "note": "Настройка режима сама по себе не подтверждает успешный вызов Gemini или Agent Engine."}


@app.get("/api/workspace")
def get_workspace(request: Request):
    data = workspace(request.state.sid)
    data["materials"] = [{k: m[k] for k in ("id", "name", "page_count", "uploaded_at")} for m in data["materials"]]
    data["history"] = (store.get(request.state.sid, "meta", "history") or {}).get("turns", [])
    for turn in data["history"]:
        if turn.get("role") == "model" and not turn.get("why"):
            turn["text"] = "Сохранён ответ предыдущей версии без карточек источников. Задайте вопрос ещё раз для проверяемого ответа."
            turn["why"] = {"title": "Почему старый ответ скрыт", "source": "История v0.1", "result": "В записи нет источников нового формата. Система не выдаёт её за проверенный ответ."}
    data["progress"] = progress(data["tasks"], data["preferences"], quest_rewards=data["quest_rewards"])
    data["google"] = connection_status(store, request.state.sid)
    data["quests"] = [{"id": q["id"], "material": q["material"], "answered": len(q["answers"]), "total": len(q["questions"])} for q in store.list(request.state.sid, "quests")]
    data["metrics"] = metrics(data["tasks"])
    data["tasks"] = [{**t, "why": task_proof(t)} for t in data["tasks"]]
    return data


@app.post("/api/tasks", status_code=201)
def add_task(body: TaskInput, request: Request):
    sid = request.state.sid
    if len(store.list(sid, "tasks")) >= 100:
        raise HTTPException(400, "В первой версии доступно до 100 заданий")
    task = {**body.model_dump(mode="json"), "id": uuid.uuid4().hex, "completed": False,
            "created_at": datetime.now(timezone.utc).isoformat()}
    if task.get("source"):
        try:
            task["source"] = validate_source(store.list(sid, "materials"), task["source"])
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    store.put(sid, "tasks", task["id"], task)
    return {**task, "why": task_proof(task)}


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, request: Request):
    task = store.update(request.state.sid, "tasks", task_id, lambda t: complete_task(t, body.completed))
    if not task:
        raise HTTPException(404, "Задание не найдено")
    return {**task, "why": task_proof(task)}


@app.put("/api/tasks/{task_id}")
def edit_task(task_id: str, body: TaskInput, request: Request):
    payload = body.model_dump(mode="json")
    if body.source:
        try:
            payload["source"] = validate_source(store.list(request.state.sid, "materials"), body.source.model_dump())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    task = store.update(request.state.sid, "tasks", task_id, lambda t: {**t, **payload})
    if not task:
        raise HTTPException(404, "Задание не найдено")
    return {**task, "why": task_proof(task)}


@app.delete("/api/tasks/{task_id}", status_code=204)
def delete_task(task_id: str, request: Request):
    if not store.delete(request.state.sid, "tasks", task_id):
        raise HTTPException(404, "Задание не найдено")


@app.put("/api/preferences")
def preferences(body: Preferences, request: Request):
    if body.end_hour <= body.start_hour or any(b.end <= b.start for b in body.busy):
        raise HTTPException(422, "Конец интервала должен быть позже начала")
    value = body.model_dump(mode="json")
    store.put(request.state.sid, "meta", "preferences", value)
    return value


@app.get("/api/plan")
async def plan(request: Request):
    data = workspace(request.state.sid)
    if connection_status(store, request.state.sid)["connected"]:
        try:
            data["calendar_cache"] = await sync_calendar(store, request.state.sid, data["preferences"])
        except ValueError as exc:
            raise HTTPException(503, str(exc)) from exc
    data = with_calendar(data)
    result = plan_week(data["tasks"], data["preferences"])
    result["calendar"] = data.get("calendar_cache")
    return result


@app.get("/api/plan/calendar.ics")
async def export_plan(request: Request):
    return Response(calendar_export(await plan(request)), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="campuspulse-week.ics"'})


def extract_material(raw, filename):
    if filename.lower().endswith(".pdf"):
        if not raw.startswith(b"%PDF-"):
            raise ValueError("Файл не является PDF")
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError("PDF защищён паролем. Загрузите открытую копию")
        if len(reader.pages) > 20:
            raise ValueError("Лимит первой версии — 20 страниц на материал")
        texts = [p.extract_text() or "" for p in reader.pages]
    else:
        texts = [raw.decode("utf-8-sig")]
    if not any(t.strip() for t in texts):
        raise ValueError("В файле нет извлекаемого текста. Сканам PDF сначала нужен OCR")
    if sum(len(t) for t in texts) > 60000:
        raise ValueError("Слишком много текста: загрузите материал частями до 60 000 символов")
    return [{"page": i + 1, "text": text} for i, text in enumerate(texts)]


@app.post("/api/materials", status_code=201)
async def upload_material(request: Request, file: UploadFile):
    name = Path(file.filename or "material").name[:160]
    if Path(name).suffix.lower() not in {".pdf", ".txt", ".md"}:
        raise HTTPException(400, "Поддерживаются PDF, TXT и MD")
    raw = await file.read(5 * 1024 * 1024 + 1)
    await file.close()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(413, "Размер файла не должен превышать 5 МБ")
    materials = store.list(request.state.sid, "materials")
    if len(materials) >= 10:
        raise HTTPException(400, "Лимит — 10 материалов. Удалите ненужные файлы")
    try:
        pages = await asyncio.to_thread(extract_material, raw, name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "Файл повреждён или текст не удалось прочитать") from exc
    material = {"id": uuid.uuid4().hex, "name": name, "pages": pages, "page_count": len(pages),
                "uploaded_at": datetime.now(timezone.utc).isoformat()}
    store.put(request.state.sid, "materials", material["id"], material)
    return {k: material[k] for k in ("id", "name", "page_count", "uploaded_at")}


@app.get("/api/materials/{material_id}")
def read_material(material_id: str, request: Request):
    material = store.get(request.state.sid, "materials", material_id)
    if not material:
        raise HTTPException(404, "Материал не найден")
    return material


@app.delete("/api/materials/{material_id}", status_code=204)
def delete_material(material_id: str, request: Request):
    if not store.delete(request.state.sid, "materials", material_id):
        raise HTTPException(404, "Материал не найден")


def remote_run(message, context, history):
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    name = os.getenv("ENGINE_RESOURCE_NAME", "")
    match = re.fullmatch(r"projects/([a-z0-9-]+)/locations/([a-z0-9-]+)/reasoningEngines/([a-zA-Z0-9_-]+)", name)
    if not match:
        raise ValueError("Не задан корректный ENGINE_RESOURCE_NAME")
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    with AuthorizedSession(credentials) as session:
        response = session.post(f"https://{match.group(2)}-aiplatform.googleapis.com/v1/{name}:query",
                                json={"class_method": "query", "input": {
                                    "message": message, "context": context, "history": history}}, timeout=160)
        response.raise_for_status()
        result = response.json()["output"]
    if not isinstance(result, dict) or "answer" not in result or "trace" not in result:
        raise ValueError("Agent Engine вернул неожиданный формат")
    result["mode"] = "remote"
    return result


@app.post("/api/chat")
async def chat(body: ChatInput, request: Request):
    sid = request.state.sid
    if sid in active_sessions or chat_slots.locked():
        raise HTTPException(429, "Предыдущий запрос ещё обрабатывается. Подождите немного")
    active_sessions.add(sid)
    try:
        async with chat_slots, asyncio.timeout(175):
            context = workspace(sid)
            history = (store.get(sid, "meta", "history") or {}).get("turns", [])
            mode = effective_mode()
            result = await calendar_dialogue(body.message, store, sid, context["preferences"])
            context["user_message"] = body.message
            context["scenario_input"] = scenario_from_message(body.message, context["preferences"]) or (context.get("scenario_input") if "сценари" in body.message.lower() else None)
            code = re.search(r"```(python|json)\s*\n([\s\S]*?)```", body.message)
            if code:
                context["diagnostic_request"] = {"code": code[2], "language": code[1], "filename": "chat.py" if code[1] == "python" else "chat.json"}
            if result is None and connection_status(store, sid)["connected"]:
                context["calendar_cache"] = await sync_calendar(store, sid, context["preferences"])
            context = with_calendar(context)
            if result is not None:
                pass
            elif mode == "remote":
                result = await asyncio.to_thread(remote_run, body.message, context, history)
            elif mode == "gemini":
                result = await gemini_run(body.message, context, history)
            elif mode == "tools":
                result = await tools_only_run(body.message, context)
            else:
                raise ValueError("Неизвестный режим AGENT_MODE")
            history += [{"role": "user", "text": body.message}, {"role": "model", "text": result["answer"],
                         "why": result.get("why"), "evidence": result.get("evidence", []), "calendar": result.get("calendar"), "mode": result["mode"], "model": result.get("model")}]
            store.put(sid, "meta", "history", {"turns": history[-12:]})
            result["run_id"] = uuid.uuid4().hex
            return result
    except TimeoutError as exc:
        raise HTTPException(504, "Превышено время запроса. Попробуйте более короткую задачу") from exc
    except ValueError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        # Never leak upstream exceptions, tokens, or uploaded text to server logs.
        raise HTTPException(503, "Агент недоступен. Проверьте выбранную модель и подключение; ответ не был сгенерирован") from exc
    finally:
        active_sessions.discard(sid)


@app.delete("/api/workspace", status_code=204)
def clear_workspace(request: Request):
    if request.state.sid in active_sessions:
        raise HTTPException(409, "Дождитесь окончания текущего запроса")
    store.clear(request.state.sid)


register_features(app, lambda: store, workspace)
app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")


@app.exception_handler(HTTPException)
async def explain_http_error(request, exc):
    return JSONResponse({"detail": exc.detail, "why": {"title": "Почему запрос не выполнен", "source": "Проверка запроса сервером", "result": exc.detail}}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def explain_validation(request, exc):
    fields = [".".join(str(x) for x in e["loc"]) for e in exc.errors()]
    return JSONResponse({"detail": "Проверьте поля: " + ", ".join(fields), "why": {"title": "Почему данные не приняты", "source": "Правила формы → campuspulse/models.py", "result": fields}}, status_code=422)


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")
