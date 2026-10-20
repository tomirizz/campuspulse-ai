import base64
import json
import os
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from scripts import start_public_demo as demo


SECRET = "private-existing-provider-key-never-render"


@pytest.fixture(autouse=True)
def restore_environment(monkeypatch):
    # The launcher intentionally configures its process. Keep tests isolated.
    before = dict(os.environ)
    yield
    for key in set(os.environ) - set(before):
        os.environ.pop(key, None)
    os.environ.update(before)


def auth(password, username="campus"):
    value = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": "Basic " + value}


def fake_app():
    app = FastAPI()
    calls = []

    @app.middleware("http")
    async def count(request: Request, call_next):
        calls.append((request.method, request.url.path, request.headers.get("authorization")))
        return await call_next(request)

    @app.get("/api/health")
    def health():
        return {"ok": True, "mode": os.environ["AGENT_MODE"]}

    @app.post("/api/mutate")
    def mutate():
        return {"saved": True}

    return app, calls


def test_environment_is_isolated_and_original_data_and_dotenv_are_not_copied(tmp_path, monkeypatch, capsys):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "data").mkdir()
    (root / "data" / "campuspulse.db").write_bytes(b"PRIVATE_ORIGINAL_WORKSPACE")
    source = "GEMINI_API_KEY=" + SECRET + "\nGOOGLE_CLOUD_PROJECT=old-project\nENGINE_RESOURCE_NAME=old-engine\nGOOGLE_OAUTH_CLIENT_ID=old-id\nGOOGLE_OAUTH_CLIENT_SECRET=old-secret\n"
    (root / ".env").write_text(source, encoding="utf-8")
    monkeypatch.delenv("PUBLIC_DEMO_AGENT_MODE", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = demo.configure_demo_environment(root)
    assert config["port"] == 8770 and config["mode"] == "tools"
    assert Path(os.environ["DATA_DIR"]) == root / "data" / "public-demo"
    assert not list((root / "data" / "public-demo").iterdir())
    assert (root / "data" / "campuspulse.db").read_bytes() == b"PRIVATE_ORIGINAL_WORKSPACE"
    assert (root / ".env").read_text(encoding="utf-8") == source
    assert os.environ["COOKIE_SECURE"] == "true" and os.environ["STORAGE_BACKEND"] == "sqlite"
    assert all(os.environ[name] == "" for name in ("GOOGLE_CLOUD_PROJECT", "ENGINE_RESOURCE_NAME", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"))
    demo.load_dotenv(root / ".env", override=False)
    assert not os.environ["GOOGLE_CLOUD_PROJECT"] and not os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
    assert SECRET not in json.dumps(config) and not capsys.readouterr().out


def test_access_file_is_generated_once_and_never_printed(tmp_path, capsys):
    path = tmp_path / "data" / "public-demo-access.json"
    first = demo.load_or_create_access(path)
    assert first["username"] == "campus" and len(first["password"]) >= 32
    assert demo.load_or_create_access(path) == first
    assert json.loads(path.read_text()) == first
    captured = capsys.readouterr()
    assert first["password"] not in captured.out + captured.err
    assert first["password"] not in os.environ.values()


@pytest.mark.parametrize("path,method", [("/", "get"), ("/assets/app.js", "get"), ("/api/docs", "get"),
                                        ("/api/workspace", "get"), ("/api/mutate", "post"), ("/api/workspace", "delete")])
def test_unauthenticated_requests_never_reach_application_or_mutate(tmp_path, path, method):
    app, calls = fake_app()
    wrapped = demo.create_demo_app(root=tmp_path, application=app)
    with TestClient(wrapped, base_url="https://demo.example") as client:
        response = getattr(client, method)(path)
        assert response.status_code == 401 and response.headers["www-authenticate"].startswith("Basic ")
        assert "set-cookie" not in response.headers
    assert calls == []


def test_authentication_accepts_only_correct_credentials_and_does_not_forward_secret(tmp_path):
    app, calls = fake_app()
    wrapped = demo.create_demo_app(root=tmp_path, application=app)
    password = json.loads((tmp_path / "data" / "public-demo-access.json").read_text())["password"]
    with TestClient(wrapped, base_url="https://demo.example") as client:
        for headers in ({}, auth("incorrect"), auth(password, "wrong-user"), {"Authorization": "Basic invalid!"},
                        {"Authorization": "Bearer " + password}):
            response = client.post("/api/mutate", headers=headers)
            assert response.status_code == 401 and password not in response.text
        result = client.get("/api/health", headers=auth(password))
        assert result.status_code == 200 and result.json()["mode"] == "tools"
        assert password not in result.text and SECRET not in result.text
    assert calls == [("GET", "/api/health", None)]


def test_constant_time_comparisons_are_both_evaluated(monkeypatch):
    calls = []
    original = demo.hmac.compare_digest

    def compare(a, b):
        calls.append((a, b))
        return original(a, b)

    monkeypatch.setattr(demo.hmac, "compare_digest", compare)
    gate = demo.BasicAuthGate(None, "campus", "strong-password-for-tests")
    assert not gate._authorized([(b"authorization", b"Basic " + base64.b64encode(b"wrong:wrong"))])
    assert len(calls) == 2


def test_explicit_open_demo_does_not_challenge_or_forward_authorization(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_ACCESS", "open")
    app, calls = fake_app()
    wrapped = demo.create_demo_app(root=tmp_path, application=app)
    with TestClient(wrapped, base_url="https://demo.example") as client:
        response = client.get("/api/health", headers={"Authorization": "Basic old-browser-cache"})
        assert response.status_code == 200
        assert "www-authenticate" not in response.headers
    assert calls == [("GET", "/api/health", None)]


def test_access_mode_must_be_explicit(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_ACCESS", "typo")
    app, _ = fake_app()
    with pytest.raises(ValueError, match="explicitly open"):
        demo.create_demo_app(root=tmp_path, application=app)


def test_open_demo_preserves_upload_size_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_DEMO_ACCESS", "open")
    app, calls = fake_app()
    wrapped = demo.create_demo_app(root=tmp_path, application=app)
    with TestClient(wrapped, base_url="https://demo.example") as client:
        response = client.post("/api/mutate", content=b"x", headers={"Content-Length": str(demo.MAX_BODY_BYTES + 1)})
        assert response.status_code == 413
    assert not calls


def test_modes_are_explicit_and_remote_or_missing_key_is_rejected(tmp_path, monkeypatch):
    for mode in ("remote", "auto", "invalid"):
        monkeypatch.setenv("PUBLIC_DEMO_AGENT_MODE", mode)
        with pytest.raises(ValueError):
            demo.configure_demo_environment(tmp_path)
    monkeypatch.setenv("PUBLIC_DEMO_AGENT_MODE", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="already configured"):
        demo.configure_demo_environment(tmp_path)
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setenv("PUBLIC_DEMO_MODEL", "chosen-free-model")
    assert demo.configure_demo_environment(tmp_path)["mode"] == "gemini"
    assert os.environ["GEMINI_MODEL"] == "chosen-free-model"


def test_already_loaded_original_server_cannot_be_accidentally_exposed(tmp_path, monkeypatch):
    monkeypatch.setitem(demo.sys.modules, "campuspulse.server", SimpleNamespace(app="original-private-app"))
    with pytest.raises(RuntimeError, match="new process"):
        demo.create_demo_app(root=tmp_path)
    assert not (tmp_path / "data" / "public-demo-access.json").exists()


@pytest.mark.asyncio
async def test_auth_precedes_size_check_and_oversize_content_length_never_reads_body():
    called = []

    async def app(*args):
        called.append(True)

    async def forbidden_receive():
        raise AssertionError("Body must not be read")

    gate = demo.BasicAuthGate(app, "campus", "test-password")
    for authorized, expected in ((False, 401), (True, 413)):
        headers = [(b"content-length", str(demo.MAX_BODY_BYTES + 1).encode())]
        if authorized:
            headers.append((b"authorization", auth("test-password")["Authorization"].encode()))
        messages = []

        async def send(message):
            messages.append(message)

        await gate({"type": "http", "headers": headers}, forbidden_receive, send)
        assert messages[0]["status"] == expected
    assert not called


@pytest.mark.asyncio
@pytest.mark.parametrize("declared_length", [None, b"1"])
async def test_chunked_or_lying_length_is_bounded_before_any_downstream_parsing(declared_length):
    called = []

    async def app(*args):
        called.append(True)

    events = iter([{"type": "http.request", "body": b"12345", "more_body": True},
                   {"type": "http.request", "body": b"6789", "more_body": False}])

    async def receive():
        return next(events)

    messages = []

    async def send(message):
        messages.append(message)

    headers = [(b"authorization", auth("test-password")["Authorization"].encode())]
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    gate = demo.BasicAuthGate(app, "campus", "test-password", max_body_bytes=8)
    await gate({"type": "http", "headers": headers}, receive, send)
    assert messages[0]["status"] == 413 and not called


@pytest.mark.asyncio
async def test_bounded_stream_is_replayed_exactly_and_credentials_are_stripped():
    captured = []
    events = iter([{"type": "http.request", "body": b"abc", "more_body": True},
                   {"type": "http.request", "body": b"def", "more_body": False}])

    async def receive():
        return next(events)

    async def send(message):
        pass

    async def app(scope, replay, send):
        captured.append((scope["headers"], await replay()))

    gate = demo.BasicAuthGate(app, "campus", "test-password", max_body_bytes=8)
    await gate({"type": "http", "headers": [
        (b"authorization", auth("test-password")["Authorization"].encode()), (b"cookie", b"campuspulse_session=unchanged")
    ]}, receive, send)
    assert captured == [([(b"cookie", b"campuspulse_session=unchanged")],
                         {"type": "http.request", "body": b"abcdef", "more_body": False})]


def test_demo_sessions_remain_independent_behind_shared_basic_password(tmp_path):
    import secrets

    app = FastAPI()
    values = {}

    @app.api_route("/api/value", methods=["GET", "POST"])
    async def value(request: Request):
        from fastapi.responses import JSONResponse
        sid = request.cookies.get("session") or secrets.token_hex(32)
        if request.method == "POST":
            values[sid] = (await request.json())["value"]
        response = JSONResponse({"value": values.get(sid)})
        response.set_cookie("session", sid, secure=True, httponly=True, samesite="lax")
        return response

    gate = demo.create_demo_app(root=tmp_path, application=app)
    password = json.loads((tmp_path / "data" / "public-demo-access.json").read_text())["password"]
    with TestClient(gate, base_url="https://demo.example") as first, TestClient(gate, base_url="https://demo.example") as second:
        assert first.post("/api/value", json={"value": "first only"}, headers=auth(password)).status_code == 200
        assert first.get("/api/value", headers=auth(password)).json()["value"] == "first only"
        assert second.get("/api/value", headers=auth(password)).json()["value"] is None
