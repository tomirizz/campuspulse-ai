"""Google Calendar OAuth and API boundary. Tokens never enter model context or traces."""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlsplit
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
import httpx

from campuspulse.progress import proof

SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class CalendarError(ValueError):
    pass


def oauth_config():
    base = os.getenv("APP_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise CalendarError("APP_BASE_URL должен использовать HTTPS; HTTP разрешён только на этом компьютере")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path:
        raise CalendarError("APP_BASE_URL должен содержать только адрес приложения без пути")
    return {"client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", ""), "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "redirect_uri": base + "/api/google/callback"}


def token_cipher():
    configured = os.getenv("GOOGLE_TOKEN_ENCRYPTION_KEY")
    if configured:
        return Fernet(configured.encode())
    if os.getenv("STORAGE_BACKEND", "sqlite") != "sqlite":
        raise CalendarError("Для облака настройте GOOGLE_TOKEN_ENCRYPTION_KEY через Google Secret Manager")
    path = Path(os.getenv("DATA_DIR", "data")) / ".calendar-token-key"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            os.chmod(path, 0o600)
            stream.write(Fernet.generate_key())
    except FileExistsError:
        pass
    return Fernet(path.read_bytes().strip())


def connection_status(store, sid):
    config = oauth_config()
    connected = bool(store.get(sid, "private", "google_tokens"))
    return {"provider": "Google Calendar", "configured": bool(config["client_id"] and config["client_secret"]),
            "connected": connected, "scope": SCOPE, "calendar": "primary",
            "why": proof("Статус подключения", "подключено = сохранено OAuth-разрешение пользователя; доступ проверяется каждым запросом",
            {}, "Разрешение сохранено" if connected else "Требуется вход Google", "Подключения этого браузера",
            "Событие считается добавленным только после ответа Google Calendar API. Истечение или отзыв доступа может потребовать повторного входа.")}


def begin_oauth(store, sid):
    config = oauth_config()
    if not config["client_id"] or not config["client_secret"]:
        raise CalendarError("Владелец приложения ещё не настроил вход Google Calendar. Откройте инструкцию в разделе подключений")
    token_cipher()  # Fail before redirect if encryption cannot be configured.
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    store.put(sid, "private", "oauth_state", {"state": state, "verifier": verifier, "expires": time.time() + 600})
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"], "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})


async def finish_oauth(store, sid, state, code, client=None):
    consumed = {}
    def consume(old):
        if not old.get("state") or not secrets.compare_digest(old["state"], state) or old["expires"] < time.time():
            raise CalendarError("Вход устарел или не относится к этому браузеру. Подключите Google ещё раз")
        consumed.update(old)
        return {"state": "", "expires": 0}
    if not store.update(sid, "private", "oauth_state", consume):
        raise CalendarError("Нет начатого входа в этом браузере")
    config = oauth_config()
    owned = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        response = await client.post("https://oauth2.googleapis.com/token", data={**config, "code": code,
            "code_verifier": consumed["verifier"], "grant_type": "authorization_code"})
        if response.status_code != 200:
            raise CalendarError("Google не подтвердил вход. Начните подключение заново")
        data = response.json()
        if not data.get("access_token") or SCOPE not in data.get("scope", "").split():
            raise CalendarError("Не предоставлен доступ к событиям собственного календаря")
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        encrypted = token_cipher().encrypt(json.dumps(data).encode()).decode()
        store.put(sid, "private", "google_tokens", {"encrypted": encrypted})
    except httpx.RequestError:
        raise CalendarError("Google не ответил на запрос входа. Подключите календарь ещё раз")
    finally:
        if owned:
            await client.aclose()


class GoogleCalendar:
    def __init__(self, store, sid, client=None):
        self.store, self.sid, self.client = store, sid, client

    async def _access_token(self, client, force=False):
        record = self.store.get(self.sid, "private", "google_tokens")
        if not record:
            raise CalendarError("Подключите Google Calendar в разделе «Подключения». Событие пока не добавлено")
        try:
            data = json.loads(token_cipher().decrypt(record["encrypted"].encode()))
        except (InvalidToken, ValueError, KeyError):
            raise CalendarError("Сохранённое разрешение недоступно. Подключите Google заново")
        if not force and data.get("expires_at", 0) > time.time() + 60:
            return data["access_token"]
        config = oauth_config()
        if not data.get("refresh_token"):
            raise CalendarError("Вход Google истёк. Подключите календарь заново")
        response = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": config["client_id"], "client_secret": config["client_secret"],
            "refresh_token": data["refresh_token"], "grant_type": "refresh_token"})
        if response.status_code != 200:
            if response.status_code in {400, 401}:
                self.store.delete(self.sid, "private", "google_tokens")
            raise CalendarError("Google не продлил разрешение. Повторно подключите календарь")
        data.update(response.json())
        data["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        self.store.put(self.sid, "private", "google_tokens", {"encrypted": token_cipher().encrypt(json.dumps(data).encode()).decode()})
        return data["access_token"]

    async def _request(self, method, suffix="", **kwargs):
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=25, follow_redirects=False)
        try:
            token = await self._access_token(client)
            response = await client.request(method, API + suffix, headers={"Authorization": "Bearer " + token}, **kwargs)
            if response.status_code == 401:
                token = await self._access_token(client, force=True)
                response = await client.request(method, API + suffix, headers={"Authorization": "Bearer " + token}, **kwargs)
            if response.status_code not in {200, 201, 204, 409}:
                reasons = {403: "Google отказал в доступе: проверьте разрешение и включение Calendar API", 404: "Календарь или событие не найдено", 429: "Лимит Google Calendar исчерпан; повторите позже"}
                raise CalendarError(reasons.get(response.status_code, "Google Calendar временно недоступен. Создание не подтверждено"))
            return response
        except httpx.RequestError:
            raise CalendarError("Нет ответа Google Calendar. Создание не подтверждено; повтор использует тот же ID и не создаёт новый дубль")
        finally:
            if owned:
                await client.aclose()

    async def events(self, start, end, tz="Asia/Almaty"):
        items, page_token = [], None
        for _ in range(10):
            params = {"timeMin": start, "timeMax": end, "singleEvents": "true", "orderBy": "startTime", "maxResults": 250}
            if page_token:
                params["pageToken"] = page_token
            response = await self._request("GET", params=params)
            data = response.json()
            for e in data.get("items", []):
                if e.get("status") == "cancelled":
                    continue
                def boundary(value):
                    if value.get("dateTime"):
                        return value["dateTime"]
                    return datetime.fromisoformat(value["date"]).replace(tzinfo=ZoneInfo(data.get("timeZone", tz))).isoformat()
                items.append({"id": e["id"], "title": e.get("summary", "Без названия"), "start": boundary(e["start"]), "end": boundary(e["end"]),
                              "busy": e.get("transparency", "opaque") != "transparent", "all_day": "date" in e["start"], "url": e.get("htmlLink", "")})
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        if page_token:
            raise CalendarError("Слишком много событий в диапазоне. Выберите меньше дней; неполные данные не используются для плана")
        fetched_at = datetime.now(timezone.utc).isoformat()
        return {"events": items, "start": start, "end": end, "fetched_at": fetched_at,
                "why": proof("Откуда события", "Google Calendar events.list; singleEvents=true; все страницы ответа в указанном диапазоне",
                {"с": start, "до": end, "получено": fetched_at}, len(items), "Google Calendar API · primary",
                "Учитывается основной календарь. События других календарей не прочитаны.")}

    async def create(self, draft):
        start, end = datetime.fromisoformat(draft["start"]), datetime.fromisoformat(draft["end"])
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise CalendarError("Проверьте дату, время и длительность события")
        body = {"id": draft["event_id"], "summary": draft["title"],
                "start": {"dateTime": start.isoformat(), "timeZone": draft["timezone"]},
                "end": {"dateTime": end.isoformat(), "timeZone": draft["timezone"]},
                "description": "Создано по явному запросу пользователя в CampusPulse." + ("\n\n" + draft["description"] if draft.get("description") else ""),
                "extendedProperties": {"private": {"campuspulseRequest": draft["event_id"]}},
                "reminders": {"useDefault": False}}
        response = await self._request("POST", json=body, params={"sendUpdates": "none"})
        if response.status_code == 409:
            response = await self._request("GET", "/" + draft["event_id"])
        value = response.json()
        if value.get("status") == "cancelled" or value.get("id") != draft["event_id"] or value.get("summary") != draft["title"]:
            raise CalendarError("Google вернул другое или удалённое событие. Проверьте его в календаре")
        for key in ("start", "end"):
            if datetime.fromisoformat(value[key]["dateTime"]) != datetime.fromisoformat(draft[key]):
                raise CalendarError("Существующее событие было изменено в Google. Проверьте время в календаре")
        return {"id": value["id"], "title": value["summary"], "start": value["start"]["dateTime"], "end": value["end"]["dateTime"],
                "url": value.get("htmlLink", ""), "status": "created",
                "why": proof("Почему событие считается добавленным", "успешный events.insert либо events.get существующего события с тем же ID и параметрами",
                {"запросы пользователя": draft["messages"], "часовой пояс": draft["timezone"], "длительность": draft["duration_minutes"]},
                {"id": value["id"], "начало": value["start"]["dateTime"], "конец": value["end"]["dateTime"]},
                value.get("htmlLink") or "Google Calendar API", "При отсутствии длительности используется сохранённая настройка пользователя. Приглашения другим людям не отправляются.")}

    async def disconnect(self):
        record = self.store.get(self.sid, "private", "google_tokens")
        revoked = False
        if record:
            try:
                data = json.loads(token_cipher().decrypt(record["encrypted"].encode()))
                async with httpx.AsyncClient(timeout=15) as client:
                    result = await client.post("https://oauth2.googleapis.com/revoke", data={"token": data.get("refresh_token") or data["access_token"]})
                    revoked = result.status_code == 200
            except (httpx.RequestError, InvalidToken, ValueError):
                pass
        self.store.delete(self.sid, "private", "google_tokens")
        self.store.delete(self.sid, "meta", "calendar_cache")
        return {"disconnected": True, "revoked": revoked,
                "why": proof("Отключение календаря", "удаление локального разрешения; запрос отзыва Google", {}, revoked, "OAuth Google",
                "События остаются в Google. Если отзыв не подтверждён, удалить разрешение можно в настройках аккаунта Google.")}
