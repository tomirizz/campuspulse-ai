"""Build an allowlisted Cloud Shell upload without secrets or personal data.

This command is entirely local: no authentication, upload, billing, IAM or
deployment operations. The archive contains the current saved source files,
including changes not committed to Git.
"""
import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parent.parent
PREFIX = "campuspulse-source"
ROOT_FILES = {"README.md", "CONTRIBUTING.md", "pyproject.toml", "requirements.lock", "Dockerfile",
              ".gcloudignore", ".dockerignore", ".gitignore", ".env.example", "mcp.json"}
DIRECTORIES = {"campuspulse": {".py"}, "scripts": {".py", ".sh", ".ps1"},
               "tests": {".py"}, "docs": {".md"},
               "web": {".html", ".css", ".js", ".json", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico", ".woff", ".woff2"},
               "assets": {".ttf", ".otf", ".woff", ".woff2", ".txt", ".md", ".svg", ".png", ".jpg", ".jpeg", ".webp", ".ico"}}
BLOCKED_PARTS = {".git", ".venv", "venv", "data", "tmp", "output", "dist", "__pycache__", ".pytest_cache", "node_modules"}


def source_files(root: Path):
    root = root.resolve()
    candidates = [root / name for name in ROOT_FILES]
    for folder in DIRECTORIES:
        location = root / folder
        if location.is_dir():
            candidates.extend(location.rglob("*"))
    selected = []
    for path in candidates:
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.resolve().relative_to(root)
        except ValueError:
            continue
        parts = relative.parts
        lower_parts = {part.casefold() for part in parts}
        if lower_parts & BLOCKED_PARTS:
            continue
        name = path.name.casefold()
        if name != ".env.example" and (name.startswith(".env") or any(part.startswith(".") for part in parts)):
            if len(parts) != 1 or path.name not in ROOT_FILES:
                continue
            if name.startswith(".env"):
                continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in ("credentials*.json", "*client_secret*.json", "*service-account*.json", "*service_account*.json", "*.db", "*.sqlite*", "*.key", "*.pem", "*.log")):
            continue
        if len(parts) > 1 and path.suffix.casefold() not in DIRECTORIES.get(parts[0], set()):
            continue
        selected.append((path, relative.as_posix()))
    return sorted(selected, key=lambda item: item[1])


def create_archive(root: Path, destination: Path, overwrite=False) -> dict:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists() and not overwrite:
        raise ValueError("Архив уже существует. Выберите другое имя либо явно добавьте --overwrite")
    if destination.suffix.casefold() != ".zip":
        raise ValueError("Имя архива должно заканчиваться на .zip")
    files = source_files(root)
    if not files:
        raise ValueError("Не найдены файлы исходного проекта")
    # The sample config must remain a sample, even if it was locally edited.
    for path, relative in files:
        if relative == ".env.example":
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" not in line or line.lstrip().startswith("#"):
                    continue
                key, value = line.split("=", 1)
                if any(word in key.upper() for word in ("SECRET", "API_KEY", "ENCRYPTION_KEY", "PASSWORD")) and value.strip():
                    raise ValueError("В .env.example найдено непустое секретное поле. Уберите его из примера перед созданием архива")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"format": "campuspulse-cloud-source-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "project_hint": "campuspulse-ai-511817", "files": []}
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, relative in files:
            payload = path.read_bytes()
            archive.writestr(f"{PREFIX}/{relative}", payload)
            manifest["files"].append({"path": relative, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()})
        archive.writestr(f"{PREFIX}/cloud-source-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return {"archive": str(destination), "files": len(files), "bytes": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "excluded": ".env, credentials, data, database, .venv, .git, tmp/output and logs are not included"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="dist/campuspulse-cloud-source.zip")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list", action="store_true", help="Only list allowlisted paths; do not create an archive")
    args = parser.parse_args()
    if args.list:
        print("\n".join(relative for _, relative in source_files(ROOT)))
        return
    destination = Path(args.output)
    if not destination.is_absolute():
        destination = ROOT / destination
    try:
        result = create_archive(ROOT, destination, overwrite=args.overwrite)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
