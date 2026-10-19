# Как работать над CampusPulse вдвоём

## 1. Принять приглашение и открыть проект

Войдите в свой GitHub-аккаунт и примите приглашение в **tomirizz/campuspulse-ai**. Репозиторий закрытый: до принятия приглашения ссылка может показывать 404.

В GitHub Desktop выберите **File → Clone repository → URL** и вставьте:

```text
https://github.com/tomirizz/campuspulse-ai.git
```

Либо клонируйте через терминал с установленным Git:

```bash
git clone https://github.com/tomirizz/campuspulse-ai.git
cd campuspulse-ai
```

Откройте полученную папку в редакторе. Это папка, в которой сразу лежат `README.md`, `pyproject.toml`, `web/`, `campuspulse/` и `scripts/`. Не клонируйте проект внутрь другой его копии.

## 2. Запустить сайт

Нужен Python 3.11–3.13; для одинакового окружения команды рекомендуем 3.11. Первая установка зависимостей требует интернета. Node.js нужен только для проверки JavaScript, а не для запуска сайта.

### Mac / Linux

В терминале из корня проекта:

```bash
bash scripts/run.sh --open
```

На Mac можно вместо этого открыть файл **«Запустить CampusPulse.command»**. Скрипт создаст окружение и установит зависимости. Если установлен `uv`, он сам подготовит Python 3.11.

### Windows

В PowerShell из корня проекта, после установки Python 3.11:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe scripts/start_web.py
```

Команды не требуют активации окружения или изменения политики PowerShell. Первые три строки выполняются при первом запуске; затем достаточно последней.

Сайт откроется по адресу **http://127.0.0.1:8765**. Остановка — **Ctrl+C** в терминале. Этот адрес работает на компьютере, где запущен проект; напарник запускает свою копию. Если порт занят старой версией, сначала остановите её.

Без настройки Google работают точные инструменты: планирование, материалы, квесты, расчёт оценок, проверка синтаксиса и подготовка календарного запроса. Настоящие ответы Gemini и запись в Google Calendar требуют подключения Google по [инструкции](docs/DEPLOYMENT.md). Облако пока отложено; чужие ключи и личный `.env` для разработки не нужны.

## 3. Вносить изменения

Перед новой задачей получите свежий `main` и создайте свою ветку. Например:

```bash
git switch main
git pull --ff-only
git switch -c feature/calendar-interface
```

Название ветки выбирайте под свою задачу. Сначала сохраните текущую работу коммитом, если уже меняли файлы. Договоритесь, кто какую часть меняет, особенно если работаете в одном файле.

После изменений проверьте сайт и сохраните только относящиеся к задаче файлы. В GitHub Desktop отметьте нужные файлы, нажмите **Commit**, затем **Publish branch / Push origin** и **Create Pull Request**. В запросе на слияние кратко напишите, что изменилось и как проверено. Второй участник сможет посмотреть изменения перед объединением с `main`. Автоматические проверки уже настроены в GitHub.

Либо используйте терминал; пути в `git add` замените на реально изменённые файлы:

```bash
git diff
git add web/features.js web/features.css
git commit -m "Improve calendar interface"
git push -u origin feature/calendar-interface
```

После слияния обновите свою основную ветку командами `git switch main` и `git pull --ff-only`.

## Где что менять

| Задача | Файлы |
|---|---|
| Внешний вид и интерфейс | `web/index.html`, CSS и JavaScript в `web/` |
| Формулы и учебные функции | `campuspulse/study.py`, `planner.py`, `progress.py`, `quests.py` |
| Календарный диалог и Google Calendar | `campuspulse/calendar_dialogue.py`, `dates.py`, `google_calendar.py` |
| Ассистент, инструменты, доказательства | `campuspulse/agent.py`, `tools.py`, `evidence.py` |
| Запросы сайта и данные | `campuspulse/server.py`, `features_api.py`, `models.py`, `storage.py` |
| Проверки и описание требований | `tests/`, `docs/REQUIREMENTS.md` |

## Проверка и общие правила

Для изменения логики запускайте тесты:

```bash
# Mac / Linux
.venv/bin/python -m pytest -q
```

```powershell
# Windows
.\.venv\Scripts\python.exe -m pytest -q
```

После изменения JavaScript, при установленном Node.js:

```bash
node --check web/app.js
node --check web/game.js
node --check web/features.js
```

- Расчёты выполняет код по формулам; числа, цитаты и результаты проверок не выдумываются моделью. Сохраняйте кнопку «Почему?» и источник результата.
- ИИ и внешние сервисы проекта — Google. Реальную облачную проверку отличаем от локальных тестов.
- `.env`, `data/`, `.venv/`, базы и учётные данные не отправляются в GitHub: они уже исключены через `.gitignore`. Не добавляйте их принудительно. Каждый участник использует свои локальные данные.
- Если изменился `requirements.lock`, обновите окружение: `.venv/bin/python -m pip install -r requirements.lock`; на Windows используйте `.\.venv\Scripts\python.exe`.
- Презентацию пока не обновляем: она запланирована после готовности продукта.
