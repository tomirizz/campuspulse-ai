"""Local image OCR. Uploaded documents are data and never executable instructions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def extract_image(raw: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Для изображения поддерживаются PNG и JPG")
    if not (raw.startswith(b"\x89PNG\r\n\x1a\n") or raw.startswith(b"\xff\xd8\xff")):
        raise ValueError("Файл не является изображением PNG/JPG")
    with tempfile.TemporaryDirectory(prefix="campuspulse-ocr-") as folder:
        path = Path(folder) / ("document" + suffix)
        path.write_bytes(raw)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        if os.name == "nt":
            script = Path(__file__).resolve().parent.parent / "scripts" / "ocr_image.ps1"
            command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                       "-File", str(script), "-ImagePath", str(path)]
            try:
                result = subprocess.run(command, capture_output=True, timeout=45, creationflags=flags)
                if result.returncode == 0:
                    value = json.loads(result.stdout.decode("utf-8-sig"))
                    if value.get("text", "").strip():
                        return {"text": value["text"][:60000], "method": "Windows OCR (локально)",
                                "warning": "Текст распознан с изображения. Сверьте числа и веса с оригиналом перед сохранением."}
            except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, UnicodeDecodeError):
                pass
        executable = shutil.which("tesseract")
        if executable:
            try:
                result = subprocess.run([executable, str(path), "stdout", "-l", "eng", "--psm", "6"],
                                        capture_output=True, timeout=45, creationflags=flags)
                text = result.stdout.decode("utf-8", errors="replace").strip()
                if result.returncode == 0 and text:
                    return {"text": text[:60000], "method": "Tesseract OCR (локально)",
                            "warning": "Проверьте распознанные числа и названия по оригиналу."}
            except (OSError, subprocess.TimeoutExpired):
                pass
    raise ValueError("Не удалось распознать изображение. Вставьте текст таблицы либо загрузите PDF с выделяемым текстом. Для сканов нужен доступный Windows OCR или Tesseract.")
