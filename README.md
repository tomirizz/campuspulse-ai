# CampusPulse AI

Учебный помощник для кейса GDG Astana: **силлабус → нужная оценка → план подготовки → конспект с источниками**.

Студент загружает правила оценивания, проверяет найденные веса и вносит оценки. CampusPulse рассчитывает достижимую цель, показывает требования к оставшимся работам и распределяет свободное время. По лекциям можно собрать конспект, проверить себя и скачать PDF.

## Hackathon submission: Agent, MCP, deployment and setup

Этот репозиторий содержит исходный код агента, конфигурацию настоящего MCP-сервера, скрипт развёртывания Vertex AI Reasoning Engine и инструкции установки ниже.

| Требование кейса | Файлы и реализация |
|---|---|
| **Source code of the agent** | [campuspulse/agent.py](campuspulse/agent.py): `gemini_run` и класс `CampusPulseAgent` для удалённого `query` |
| **MCP configuration** | [mcp.json](mcp.json), [campuspulse/mcp_server.py](campuspulse/mcp_server.py): FastMCP, транспорт stdio, инструмент `current_time` |
| **Custom Tools / Function Calling** | [campuspulse/tools.py](campuspulse/tools.py): JSON Schema, обнаружение MCP-инструментов и выполнение разрешённых функций |
| **Reasoning Engine deployment script** | [scripts/deploy_agent.py](scripts/deploy_agent.py): `reasoning_engines.ReasoningEngine.create`, обновление существующего ресурса через `--update` |
| **Deployment verification** | [scripts/verify_cloud.py](scripts/verify_cloud.py): реальный удалённый запрос, проверка выполненных инструментов, запись результата |
| **Setup instructions** | Этот README: Python 3.11, установка зависимостей, Gemini, MCP, локальный запуск и облачный путь |
| **Frontend / demo client** | [web/](web/), [campuspulse/server.py](campuspulse/server.py): интерфейс, FastAPI, сессии и журнал вызовов |
| **Presentation** | [Финальная презентация PowerPoint](docs/presentation/CampusPulse-AI-FINAL.pptx), [PDF-копия](docs/presentation/CampusPulse-AI-FINAL.pdf) |

### Архитектура и цикл агента

```text
Веб-интерфейс
    -> FastAPI и данные сессии
    -> Gemini выбирает инструмент
    -> ToolHub проверяет аргументы
        -> MCP stdio: current_time
        -> Function Calling: оценки, план, поиск по материалам
    -> результат инструмента возвращается Gemini
    -> следующий вызов или ответ с проверяемыми фактами
```

Модель выбирает действия, а код рассчитывает числа и формулы. Вызовы ограничены восемью раундами и двенадцатью инструментами. Журнал показывает название инструмента, аргументы, результат, длительность и транспорт. Он не раскрывает скрытые рассуждения модели. Документы и загруженный текст не могут разрешать внешние действия.

## 1. Установка и локальный запуск

Нужен Python 3.11; первая установка требует интернета.

- Windows: откройте **«Запустить CampusPulse.bat»**.
- macOS: откройте **«Запустить CampusPulse.command»**.
- Linux/macOS в терминале: `bash scripts/run.sh`.

Адрес: <http://127.0.0.1:8765>. Терминал должен оставаться открытым; остановка — Ctrl+C. Перед запуском обновлённой версии остановите старую.

В PowerShell команды выполняются отдельными строками:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.\.venv\Scripts\python.exe scripts/start_web.py
```

В следующие разы достаточно последней команды.

Для macOS/Linux без стартового файла, из корня репозитория:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
if [ ! -f .env ]; then cp .env.example .env; fi
.venv/bin/python scripts/start_web.py
```

Не запускайте несколько копий на одном порту. После изменения `.env` остановите сервер и запустите его заново. Без Google credentials режим `auto` выбирает явно обозначенные локальные инструменты; платный облачный аккаунт для этого не нужен.

## 2. Демонстрация за минуту

1. На экране «Моя учёба» нажмите **«Посмотреть пример»**.
2. Появятся четыре разных предмета, оценки, занятия и материалы, явно помеченные как пример.
3. Откройте «Внести оценки» и измените балл: цель и план пересчитаются.
4. Нажмите «Готовиться»: откроются связанные материалы, конспект и самопроверка.
5. В календаре добавьте своё событие: занятое время исключается из учебного плана.

**«Убрать пример» удаляет только данные, созданные этим примером**, сохраняя ваши предметы, материалы, настройки и события. Чистый старт не содержит вымышленных личных оценок.

## Возможности

| Раздел | Что работает |
|---|---|
| Моя учёба | Силлабус из текста/PDF/фото, подтверждение весов, несколько предметов, кредиты, оценки и настраиваемая шкала GPA |
| Нужная оценка | Взвешенная сумма, достижимый максимум, лестница целей 95→90→85…, совместный план оставшихся баллов и условные минимумы |
| Учебный план | Свободные интервалы, дедлайны, сложность, кредиты и риск; блоки подготовки с перерывами |
| Конспекты | Выжимка по источникам, понятия, вопросы и цитаты; скачивание PDF, HTML, Markdown и TXT |
| Календарь | Неделя/месяц, важные дела, отдельные и еженедельные локальные события, импорт расписания и ICS |
| Google Calendar | OAuth-вход, чтение занятости, отправка отдельного события по явному нажатию |
| Ассистент | Gemini с выбором инструментов и журналом фактических вызовов; явный режим без ИИ |
| Дополнительно | Задания, поиск по материалам, учебные квесты, проверка синтаксиса Python/JSON без исполнения кода |

Силлабус сохраняется как источник и используется для подготовки без повторной загрузки. Неполные правила требуют проверки: скрытые веса и сроки не подставляются.

## 3. Настройка Google Gemini

Расчёты, план, локальный календарь и извлечение цитат работают без платного облака.

Для настоящего Gemini владелец приложения открывает **«Подключить Gemini.bat»** и вставляет ключ Google AI Studio в скрытое поле. Ключ остаётся в локальном `.env`, не передаётся браузеру и не публикуется. После настройки перезапустите сайт. Альтернатива — Vertex AI с серверными Application Default Credentials.

Владелец получает собственный ключ в [Google AI Studio](https://aistudio.google.com/api-keys), как описано в [инструкции Google](https://ai.google.dev/gemini-api/docs/api-key). Ключ не нужно отправлять в чат или добавлять в GitHub.

После сохранения ключа задайте в своём `.env` выбранный режим и модель. Проверенная модель нашей демонстрации:

```dotenv
AGENT_MODE=gemini
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=YOUR_OWN_GOOGLE_AI_STUDIO_KEY
```

`YOUR_OWN_GOOGLE_AI_STUDIO_KEY` заменяется личным ключом только на сервере. В `.env.example` и локальном конфигураторе может быть другая модель, поэтому проверьте `GEMINI_MODEL` после настройки. Доступ к моделям зависит от провайдера и проекта. Если раньше вы задавали `AGENT_MODE` или `GEMINI_MODEL` через переменные PowerShell, они имеют приоритет над `.env`.

Из установленного окружения можно проверить MCP и наличие настройки, затем отдельно выполнить настоящий запрос Gemini:

```powershell
.\.venv\Scripts\python.exe -m scripts.preflight
.\.venv\Scripts\python.exe -m scripts.preflight --live
```

Первая команда проверяет настоящий MCP-протокол; при отсутствии API-ключа также проверяет ADC. Она не подтверждает, что ключ имеет рабочую квоту. `--live` делает запрос Google и расходует квоту; возможная оплата зависит от настроек проекта. `/api/health` показывает выбранный режим и модель, но сам по себе не подтверждает доступность провайдера.

Без доступа к Gemini конспект является **извлечённой выжимкой, а не ответом нейросети**. Способ подготовки виден в интерфейсе. При подключённом Gemini используются структурированные ответы и цитаты; сбой провайдера не выдаётся за успешный ответ ИИ.

Для бесплатного запуска проект API-ключа должен оставаться на Free tier без billing. Привязка платёжного аккаунта может изменить тариф всех его ключей; поэтому бесплатный ключ и будущий облачный деплой лучше держать в разных проектах. Бесплатная квота ограничена; приложение не включает оплату и не переключает тариф автоматически. [Правила Google](https://ai.google.dev/gemini-api/docs/billing).

В демонстрации проверен живой запрос Gemini `gemini-3.1-flash-lite`, вызвавший `current_time` по MCP stdio и `study_progress` через Function Calling. Отдельно проверен Gemini-конспект с сохранёнными цитатами. Это сетевые проверки, отличные от локальных автоматических тестов. Сбой 503 может означать временную перегрузку Google, а не неверный ключ. Лимит одного запроса провайдеру — 45 секунд; для отдельных временных серверных ошибок разрешён один повтор. Ошибки ключа и квоты автоматически не повторяются.

### Режимы работы

| `AGENT_MODE` | Поведение |
|---|---|
| `auto` | Agent Engine при заданном `ENGINE_RESOURCE_NAME`, иначе доступный Gemini, иначе локальные инструменты |
| `gemini` | Настоящий Gemini: серверный Developer API key либо Vertex AI ADC |
| `remote` | Вызов ранее развёрнутого Vertex AI Agent Engine |
| `tools` | Явный режим без языковой модели: точные расчёты, план и работа с источниками |

## 4. MCP configuration и собственные инструменты

### MCP-сервер

[campuspulse/mcp_server.py](campuspulse/mcp_server.py) запускает отдельный FastMCP-процесс по **stdio**. Он предоставляет `current_time(timezone_name)`: текущие дату и время с IANA timezone. Клиент в [ToolHub](campuspulse/tools.py) делает `initialize`, `list_tools` и `call_tool`. Это реальное MCP-соединение, а не список функций, названный MCP.

Внутри приложения сервер запускается автоматически текущим Python-интерпретатором (`sys.executable`). Отдельно настраивать MCP-клиент для обычного запуска сайта не нужно.

Для внешнего MCP-клиента [mcp.json](mcp.json) содержит macOS/Linux-команду `.venv/bin/python`. Клиент нужно запускать из корня репозитория. Эквивалент для Windows:

```json
{
  "mcpServers": {
    "campuspulse": {
      "command": ".venv\\Scripts\\python.exe",
      "args": ["-m", "campuspulse.mcp_server"]
    }
  }
}
```

Если MCP-клиент запускается из другой папки, задайте в его настройках рабочую папку репозитория либо абсолютные пути к Python и модулю. При прямом запуске `python -m campuspulse.mcp_server` процесс ожидает JSON-RPC по stdin, а не открывает сайт. Не добавляйте обычные сообщения `print` в stdout этого сервера.

### Function Calling

Это отдельные разрешённые функции с проверкой аргументов, а не дополнительные MCP-серверы:

| Инструмент | Назначение |
|---|---|
| `academic_overview` | Текущие баллы, достижимые цели, GPA и приоритеты |
| `academic_plan` | Подготовка по свободным окнам с учётом занятости и сроков |
| `syllabus_weights` | Извлечение схемы оценивания для подтверждения пользователем |
| `list_materials`, `read_material`, `search_materials` | Поиск и чтение материалов своей сессии с цитатами |
| `study_progress` | XP, уровень и правила начисления |
| `list_tasks`, `plan_week` | Задания и распределение нагрузки |

Полный список и схемы: [campuspulse/tools.py](campuspulse/tools.py), [docs/TOOLS.md](docs/TOOLS.md). Произвольное исполнение кода, чтение файлов ноутбука и автоматическая запись в Google Calendar не предоставлены модели как инструменты.

## 5. Reasoning Engine deployment script

Скрипт [scripts/deploy_agent.py](scripts/deploy_agent.py) использует API из требования кейса:

```python
from vertexai.preview import reasoning_engines

remote = reasoning_engines.ReasoningEngine.create(**kwargs, sys_version="3.11")
```

В `kwargs` передаются `CampusPulseAgent`, pinned-зависимости из `requirements.lock`, пакет `campuspulse` и метаданные. Скрипт сохраняет настоящее имя ресурса в `deployment.json`. Это пример используемого API; полная исполняемая реализация находится в файле скрипта. [Справочник Google ReasoningEngine](https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai.preview.reasoning_engines.ReasoningEngine).

### Предварительные условия

Облачный путь требует отдельного решения владельца проекта: активный billing, доступ к Vertex AI, включённые Vertex AI и Cloud Storage API, существующий staging bucket `gs://...` и нужные права пользователя/runtime identity. Google AI Studio key не заменяет Vertex AI ADC. [Требования Google к окружению](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/set-up?hl=id).

**Команды ниже могут создавать платный ресурс. Они не выполняются автоматически при локальном запуске.** Текущая демоверсия использует FastAPI; Agent Engine — следующий этап развёртывания, а не заявленный работающий облачный endpoint.

### Создать и проверить облачного агента

Команды для macOS/Linux или подготовленного Cloud Shell, из корня проекта. Сначала установите Python 3.11 и зависимости, как описано выше. Замените `YOUR_PROJECT_ID`, `YOUR_EXISTING_STAGING_BUCKET` и `YOUR_VERTEX_MODEL_ID` реальными значениями. Модель должна быть доступна именно в вашем Vertex AI-проекте; успешный Developer API-вызов не подтверждает её доступность в Vertex AI.

```bash
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="us-central1"
export GEMINI_LOCATION="global"
export GEMINI_MODEL="YOUR_VERTEX_MODEL_ID"
export GEMINI_API_KEY=""

gcloud auth application-default login
.venv/bin/python -m scripts.preflight --live

.venv/bin/python -m scripts.deploy_agent \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --bucket "gs://YOUR_EXISTING_STAGING_BUCKET" \
  --region "$GOOGLE_CLOUD_LOCATION" \
  --gemini-location "$GEMINI_LOCATION" \
  --model "$GEMINI_MODEL"

.venv/bin/python -m scripts.verify_cloud
```

`--model` указан явно, чтобы не зависеть от значения по умолчанию скрипта. Для обновления существующего агента добавьте `--update projects/PROJECT_NUMBER/locations/REGION/reasoningEngines/ENGINE_ID`, используя реальный ресурс, а не создавая дубликат.

Проверка `verify_cloud` делает удалённый запрос и требует успешных `current_time` и `study_progress`. Только после успеха она устанавливает `api_verified=true` в `deployment.json` и сохраняет результат в `evidence/live-cloud.json`. Создание ресурса и работоспособность API проверяются отдельно.

Чтобы локальный UI вызывал проверенный агент, задайте в серверном `.env` `AGENT_MODE=remote`, `GOOGLE_CLOUD_PROJECT` и `ENGINE_RESOURCE_NAME` из `deployment.json`, настройте ADC для этого компьютера и перезапустите сайт. Авторизация Cloud Shell не переносится на ноутбук автоматически.

Пошаговая подготовка bucket/API, отдельное развёртывание web-клиента и Firestore: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Для Cloud Shell также есть [scripts/cloud_shell_agent.sh](scripts/cloud_shell_agent.sh) с отдельными командами `check`, `prepare`, `deploy`, `verify`. `prepare` меняет облачные ресурсы, а `deploy`/`verify` расходуют квоту. Этот README не подтверждает, что они уже выполнены.

## 6. Календарь и HTTPS-демо

Локальный календарь работает без Google OAuth. Google Calendar подключается отдельно кнопкой входа. Владелец настраивает Calendar API и OAuth Web Client; [инструкция](docs/DEPLOYMENT.md). Повторяющиеся события пока локальные; в Google отправляется отдельная запись. Уже отправленное событие редактируется и удаляется в Google Calendar.

Для временного показа подготовлен [scripts/start_public_demo.py](scripts/start_public_demo.py). Он использует отдельную папку `data/public-demo`, отключает Google OAuth и не копирует личное пространство. По умолчанию вход защищён паролем; режим `PUBLIC_DEMO_ACCESS=open` явно открывает демо любому, у кого есть URL. HTTPS-туннель подключается отдельно к `127.0.0.1:8770`. Ноутбук, сервер и туннель должны оставаться включёнными. Такой показ не заменяет развёртывание в Agent Engine.

## Кейс хакатона и честные границы

В репозитории есть Gemini-агент, собственный MCP-сервер, Function Calling, развёртывание через `reasoning_engines.ReasoningEngine.create`, Cloud Run и адаптер Firestore.

**Скрипт не означает выполненный облачный деплой.** Для облачной части кейса нужны billing, права проекта, реальный запуск Agent Engine и проверка API. OAuth-конфигурация также не заменяет вход пользователя и успешную проверку Calendar.

Оценки считает код, не модель. «Текущий результат» — среднее только по сданным работам, не итоговая оценка. Целевой GPA — сценарий, не прогноз. Шкала редактируется; 70 — личная цель, не гарантия стипендии. Сложность по названию/оценкам приблизительна и изменяема.

Локальные данные хранятся в SQLite и привязаны к браузеру; синхронизации между компьютерами нет. Поиск лексический. Локальное OCR фото зависит от системы; настроенный Gemini может помочь прочитать документ. Распознанные веса всегда сверяются с оригиналом.

## 7. Тесты и структура репозитория

Проверка текущей сборки: **459 автоматических тестов** успешно пройдены 20 октября 2026 года. Сетевые запросы Gemini и облачный деплой проверяются отдельно, они не следуют из числа локальных тестов.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --check web/app.js
node --check web/academic.js
node --check web/notebook.js
node --check web/calendar_studio.js
```

```text
campuspulse/
  agent.py                 Gemini loop и CampusPulseAgent.query
  tools.py                 Function Calling и MCP client
  mcp_server.py            FastMCP stdio server
  server.py                FastAPI и границы сессии
  academic*.py             Импорт, оценки и учебный план
  notebook*.py             Конспекты и экспорт
  google_calendar.py       OAuth и Google Calendar API
web/                       Интерфейс и журнал инструментов
scripts/
  start_web.py             Локальный запуск
  deploy_agent.py          ReasoningEngine.create / update
  verify_cloud.py          Проверка реального облачного API
  preflight.py             MCP, credentials и опциональный live-запрос
mcp.json                   Конфигурация внешнего MCP-клиента
requirements.lock          Зафиксированные зависимости
.env.example               Пример конфигурации без ключей
tests/                     Автоматические проверки
docs/                      Архитектура, инструкции и презентация
```

- [Сценарий демонстрации](docs/DEMO.md)
- [Академические расчёты](docs/ACADEMIC.md)
- [Архитектура](docs/ARCHITECTURE.md) и [MCP/инструменты](docs/TOOLS.md)
- [Соответствие требованиям](docs/REQUIREMENTS.md)
- [Google Cloud и Calendar](docs/DEPLOYMENT.md)
- [Финальная презентация PDF](docs/presentation/CampusPulse-AI-FINAL.pdf), [PPTX](docs/presentation/CampusPulse-AI-FINAL.pptx)
- [Совместная работа через GitHub](CONTRIBUTING.md)

Не публикуйте `.env`, OAuth JSON, `data/` и `.venv/`. Токены Calendar зашифрованы и не передаются модели. Документ не может разрешить изменение оценок или создание внешних событий.
