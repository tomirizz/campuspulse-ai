"""Isolated local backend for an HTTPS demo tunnel; password-protected by default.

Run ``python -m scripts.start_public_demo`` in a NEW process. This does not
create a tunnel, deploy to a cloud provider or copy the student's workspace.
The password is stored only in ignored data/public-demo-access.json.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import secrets
import sys

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
PORT = 8770
USERNAME = "campus"
MAX_BODY_BYTES = 6 * 1024 * 1024


def configure_demo_environment(root: Path = ROOT) -> dict:
    """Load server configuration privately, then override isolation boundaries."""
    root = Path(root).resolve()
    load_dotenv(root / ".env", override=False)
    mode = os.getenv("PUBLIC_DEMO_AGENT_MODE", "tools").strip().lower()
    if mode not in {"tools", "gemini"}:
        raise ValueError("Public demo mode must be tools or gemini")
    if mode == "gemini" and not os.getenv("GEMINI_API_KEY"):
        raise ValueError("Gemini demo mode needs an already configured server API key")
    data_dir = root / "data" / "public-demo"
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ.update(DATA_DIR=str(data_dir), STORAGE_BACKEND="sqlite", COOKIE_SECURE="true",
                      AGENT_MODE=mode, APP_BASE_URL=f"http://127.0.0.1:{PORT}")
    # Empty values intentionally block server.load_dotenv(override=False) from
    # restoring credentials/routes from the original .env after this function.
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "ENGINE_RESOURCE_NAME",
                 "GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS"):
        os.environ[name] = ""
    if os.getenv("PUBLIC_DEMO_MODEL"):
        os.environ["GEMINI_MODEL"] = os.environ["PUBLIC_DEMO_MODEL"]
    return {"port": PORT, "mode": mode, "data_dir": str(data_dir),
            "access_file": str(root / "data" / "public-demo-access.json")}


def load_or_create_access(path: Path) -> dict:
    """Create once; never print, export through HTTP or put secrets in env vars."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            value = {"username": USERNAME, "password": secrets.token_urlsafe(24), "port": PORT,
                     "created_at": datetime.now(timezone.utc).isoformat()}
            json.dump(value, stream, ensure_ascii=False, indent=2)
    except FileExistsError:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ValueError("Public demo access file is unreadable; keep it private and repair it locally") from None
    if (not isinstance(value, dict) or value.get("username") != USERNAME
            or not isinstance(value.get("password"), str) or len(value["password"]) < 24):
        raise ValueError("Public demo access file is invalid; keep it private and repair it locally")
    return value


class BasicAuthGate:
    """Authenticate before ANY application code, including public assets/docs."""

    def __init__(self, app, username: str, password: str, *, max_body_bytes=MAX_BODY_BYTES,
                 require_auth=True):
        self.app = app
        self._username = username.encode("utf-8")
        self._password = password.encode("utf-8")
        self._max_body_bytes = max_body_bytes
        self._require_auth = require_auth

    async def _reject_body(self, send, status=413):
        body = b'{"detail":"Request body too large or invalid"}'
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"application/json"), (b"cache-control", b"no-store"),
            (b"content-length", str(len(body)).encode("ascii"))]})
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, headers):
        values = [value for key, value in headers if key.lower() == b"authorization"]
        username, password = b"", b""
        if len(values) == 1 and len(values[0]) <= 2048:
            scheme, separator, token = values[0].partition(b" ")
            if separator and scheme.lower() == b"basic":
                try:
                    decoded = base64.b64decode(token, validate=True)
                    username, separator, password = decoded.partition(b":")
                    if not separator:
                        username, password = b"", b""
                except (binascii.Error, ValueError):
                    pass
        # Evaluate BOTH constant-time comparisons, even for an invalid username.
        return bool(hmac.compare_digest(username, self._username) &
                    hmac.compare_digest(password, self._password))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.app(scope, receive, send)
        if self._require_auth and not self._authorized(scope.get("headers", [])):
            if scope["type"] == "websocket":
                return await send({"type": "websocket.close", "code": 1008})
            body = b'{"detail":"Authentication required"}'
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                (b"www-authenticate", b'Basic realm="CampusPulse demo", charset="UTF-8"'),
                (b"content-length", str(len(body)).encode("ascii"))]})
            return await send({"type": "http.response.body", "body": body})
        if scope["type"] == "http":
            lengths = [value for key, value in scope.get("headers", []) if key.lower() == b"content-length"]
            if lengths:
                try:
                    if len(lengths) != 1 or not lengths[0].isdigit():
                        raise ValueError()
                    length = int(lengths[0])
                except (ValueError, OverflowError):
                    return await self._reject_body(send, 400)
                if length > self._max_body_bytes:
                    return await self._reject_body(send)
            # Authenticate FIRST, then bound even chunked/lying-length uploads
            # before FastAPI/Starlette can parse multipart or spool files.
            body = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    return await self._reject_body(send, 400)
                chunk = message.get("body", b"")
                if len(body) + len(chunk) > self._max_body_bytes:
                    return await self._reject_body(send)
                body.extend(chunk)
                if not message.get("more_body", False):
                    break
            original_receive = receive
            delivered = False

            async def replay_receive():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await original_receive()

            receive = replay_receive
        # Never let the application, model context or an exception trace receive
        # the Basic credential. The existing session cookie remains independent.
        clean_scope = {**scope, "headers": [(key, value) for key, value in scope.get("headers", [])
                                            if key.lower() not in {b"authorization", b"proxy-authorization"}]}
        return await self.app(clean_scope, receive, send)


def create_demo_app(*, root: Path = ROOT, application=None):
    """Build the protected app. ``application`` is an offline testing seam."""
    config = configure_demo_environment(root)
    access_mode = os.getenv("PUBLIC_DEMO_ACCESS", "password").strip().lower()
    if access_mode not in {"password", "open"}:
        raise ValueError("Public demo access must be password or explicitly open")
    if application is None and "campuspulse.server" in sys.modules:
        raise RuntimeError("Start the public demo in a new process before importing campuspulse.server")
    access = load_or_create_access(Path(config["access_file"]))
    if application is None:
        from campuspulse.server import app
        application = app
    return BasicAuthGate(application, access["username"], access["password"],
                         require_auth=access_mode != "open")


def main():
    import uvicorn

    app = create_demo_app()
    print(f"CampusPulse public demo backend: 127.0.0.1:{PORT}; mode={os.environ['AGENT_MODE']}", flush=True)
    print("HTTPS tunnel required. Access mode: " + os.getenv("PUBLIC_DEMO_ACCESS", "password"), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
