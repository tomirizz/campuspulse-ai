"""Import an owner's downloaded Web OAuth config without exposing its secret."""
import argparse
import json
from pathlib import Path
import os
from urllib.parse import urlsplit

from dotenv import set_key


def import_config(source, destination, base_url="http://127.0.0.1:8765"):
    config = json.loads(Path(source).read_text(encoding="utf-8-sig"))
    web = config.get("web")
    if not web or not web.get("client_id") or not web.get("client_secret"):
        raise ValueError("Нужен JSON OAuth-клиента типа Web application")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("Укажите только адрес сайта без пути")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("HTTP разрешён только для локального приложения")
    redirect = base_url.rstrip("/") + "/api/google/callback"
    if redirect not in web.get("redirect_uris", []):
        raise ValueError("В OAuth-клиенте нет нужного Authorized redirect URI: " + redirect)
    destination = Path(destination)
    if not destination.exists():
        sample = Path(__file__).resolve().parents[1] / ".env.example"
        destination.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
    for key, value in {"GOOGLE_OAUTH_CLIENT_ID": web["client_id"], "GOOGLE_OAUTH_CLIENT_SECRET": web["client_secret"],
                       "APP_BASE_URL": base_url.rstrip("/")}.items():
        set_key(str(destination), key, value)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return {"configured": True, "project": web.get("project_id"), "redirect_uri": redirect}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("json_file")
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    try:
        result = import_config(args.json_file, args.env_file, args.base_url)
    except (ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False))
    print("Перезапустите CampusPulse. Затем нажмите «Подключить Google Calendar» и войдите в свой Google-аккаунт.")


if __name__ == "__main__":
    main()
