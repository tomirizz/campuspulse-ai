import json
from pathlib import Path
import zipfile

import pytest

from scripts.prepare_cloud_archive import create_archive


def test_cloud_upload_is_allowlisted_and_preserves_current_source(tmp_path):
    source = tmp_path / "source"
    for name in ("campuspulse", "scripts", "web", "assets/fonts", "data", ".git", "tmp"):
        (source / name).mkdir(parents=True)
    (source / "campuspulse/agent.py").write_text("# actual current source", encoding="utf-8")
    (source / "scripts/deploy_agent.py").write_text("# deploy source", encoding="utf-8")
    (source / "web/index.html").write_text("<h1>CampusPulse</h1>", encoding="utf-8")
    (source / "web/client_secret_demo.json").write_text('{"secret":"PRIVATE_OAUTH"}', encoding="utf-8")
    (source / "web/team-service_account.json").write_text('{"secret":"PRIVATE_ACCOUNT"}', encoding="utf-8")
    (source / "assets/fonts/LICENSE.txt").write_text("font license", encoding="utf-8")
    (source / ".env").write_text("GEMINI_API_KEY=PRIVATE_SECRET", encoding="utf-8")
    (source / ".env.example").write_text("GEMINI_API_KEY=\nAGENT_MODE=auto", encoding="utf-8")
    (source / "data/student.txt").write_text("PRIVATE_STUDENT_DATA", encoding="utf-8")
    (source / ".git/config").write_text("PRIVATE_GIT_CONFIG", encoding="utf-8")
    (source / "tmp/test.py").write_text("PRIVATE_QA_ARTIFACT", encoding="utf-8")
    destination = tmp_path / "upload.zip"
    result = create_archive(source, destination)
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert "campuspulse-source/campuspulse/agent.py" in names
        assert "campuspulse-source/.env.example" in names
        assert not any(name.endswith("/.env") or "/data/" in name or "/.git/" in name or "/tmp/" in name for name in names)
        assert b"PRIVATE_" not in b"".join(archive.read(name) for name in names)
        manifest = json.loads(archive.read("campuspulse-source/cloud-source-manifest.json"))
        assert len(manifest["files"]) == result["files"]


def test_archive_rejects_secret_in_sample_config_and_unintended_overwrite(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / ".env.example").write_text("GEMINI_API_KEY=do-not-package", encoding="utf-8")
    destination = tmp_path / "upload.zip"
    with pytest.raises(ValueError, match="секретное"):
        create_archive(source, destination)
    (source / ".env.example").write_text("GEMINI_API_KEY=", encoding="utf-8")
    create_archive(source, destination)
    with pytest.raises(ValueError, match="уже существует"):
        create_archive(source, destination)
