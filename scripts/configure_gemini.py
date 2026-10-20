"""Owner-only local setup. The API key is never echoed or sent through the UI."""
from getpass import getpass
from pathlib import Path
import os

from dotenv import set_key


def main():
    root = Path(__file__).resolve().parents[1]
    destination = root / ".env"
    print("CampusPulse: подключение Gemini через Google AI Studio")
    print("Создайте ключ на https://aistudio.google.com/api-keys")
    print("Ключ сохраняется только в .env этого проекта. Ввод ниже скрыт.")
    value = getpass("Вставьте Gemini API key и нажмите Enter: ").strip()
    if len(value) < 20 or any(char.isspace() for char in value):
        raise SystemExit("Значение не похоже на API-ключ. Ничего не сохранено.")
    if not destination.exists():
        destination.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    set_key(str(destination), "GEMINI_API_KEY", value)
    set_key(str(destination), "GEMINI_MODEL", "gemini-3.8-flash")
    set_key(str(destination), "AGENT_MODE", "gemini")
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    print("Ключ сохранён. Перезапустите CampusPulse и отправьте запрос в чате.")
    print("Наличие ключа ещё не подтверждает доступ: его проверит настоящий запрос к Gemini.")


if __name__ == "__main__":
    main()
