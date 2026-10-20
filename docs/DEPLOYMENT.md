# Google: подключение и Cloud Shell для CampusPulse

Целевой проект этой команды — **campuspulse-ai-511817**, регион агента — **us-central1**. Это подготовленный путь, а не отчёт об успешном развёртывании. Наличие исходников, скриптов и локальных тестов не означает, что биллинг, IAM, Gemini или Agent Engine уже доступны. В этой работе облачные ресурсы и привязка биллинга автоматически не создавались.

Для обязательного пункта кейса сначала достаточно развернуть и проверить API агента. Cloud Run, Firestore и Google Calendar — отдельные подключения; не нужно запускать их настройку одновременно с первой попыткой Agent Engine.

## Что необходимо до запуска

Владелец должен отдельно решить вопрос с биллингом. Включённым считается проект, привязанный к действующему активному платёжному аккаунту. Наличие промокредита не подтверждает такую привязку и не означает отсутствие всех возможных расходов. Здесь нет команды автоматического включения биллинга. [Проверка статуса биллинга](https://docs.cloud.google.com/billing/docs/how-to/verify-billing-enabled).

Нужен доступ к проекту и право развёртывания, обычно Vertex AI User. Подготовка API, создание bucket и выдача IAM требуют дополнительных административных прав. Если появляется Permission denied, нужно исправить конкретное отсутствующее разрешение с администратором, а не выдавать Owner всем участникам. [Права Agent Engine](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/set-up?hl=id).

| Действие | Кто должен иметь соответствующие права |
|---|---|
| Проверить проект и billingEnabled | Участник с доступом к проекту и информации биллинга |
| Включить API | Администратор с serviceusage.services.enable |
| Создать staging bucket | Администратор с storage.buckets.create |
| Записать/прочитать staging-объекты | Развёртывающий участник с правами на выбранный bucket |
| Создать/query агента | Развёртывающий участник с правами Vertex AI |
| Работать внутри агента | Google-managed Reasoning Engine Service Agent с необходимыми runtime-разрешениями |

У runtime service agent адрес вида service-PROJECT_NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com. Google назначает ему служебную роль для работы агента; при ошибках доступа администратор проверяет именно этот principal. Служебные роли не нужно раздавать человеческим пользователям. [Runtime identity и роли](https://docs.cloud.google.com/gemini-enterprise-agent-platform/scale/runtime/manage-agent-access).

## 1. Создать чистый архив на ноутбуке

Откройте терминал в актуальной папке проекта и выполните:

~~~powershell
py -3.11 -m scripts.prepare_cloud_archive
~~~

Результат — dist/campuspulse-cloud-source.zip. Скрипт только собирает локальные файлы; не загружает их и не обращается к Google. Он берёт текущие сохранённые исходники, включая ещё не закоммиченные изменения.

В архив не входят .env, .venv, data, база, .git, токены, временные PDF и логи. .env.example допустим только с пустыми секретными полями; скрипт проверяет это. Добавлены список файлов и SHA-256 в cloud-source-manifest.json.

Для просмотра списка без создания архива:

~~~powershell
py -3.11 -m scripts.prepare_cloud_archive --list
~~~

При повторной сборке уже существующего архива:

~~~powershell
py -3.11 -m scripts.prepare_cloud_archive --overwrite
~~~

## 2. Загрузить архив в Cloud Shell

Откройте Google Cloud Console под аккаунтом с доступом к campuspulse-ai-511817, затем Cloud Shell. В меню ⋮ выберите Upload и загрузите только campuspulse-cloud-source.zip. Файл попадёт в домашнюю папку Cloud Shell. [Официальная загрузка файлов](https://docs.cloud.google.com/shell/docs/uploading-and-downloading-files).

Далее выполняйте команды в Cloud Shell, а не в Windows PowerShell:

~~~bash
CAMPUSPULSE_UPLOAD_DIR="$(mktemp -d "$HOME/campuspulse-upload.XXXXXX")"
unzip "$HOME/campuspulse-cloud-source.zip" -d "$CAMPUSPULSE_UPLOAD_DIR"
cd "$CAMPUSPULSE_UPLOAD_DIR/campuspulse-source"
bash scripts/cloud_shell_agent.sh check campuspulse-ai-511817
~~~

Распаковка идёт в новую папку и не перезаписывает старые исходники. Команда check читает аккаунт, проект и статус биллинга. Она ничего не включает и не создаёт. При выключенном/непроверенном биллинге останавливается; это нельзя считать успешной проверкой.

Cloud Shell управляет авторизацией текущего Google-аккаунта. При первом запросе может потребоваться кнопка Authorize. В Cloud Shell не нужно выполнять gcloud auth application-default login и загружать JSON-ключ сервисного аккаунта. Для локального ноутбука ADC настраивается отдельно. [Авторизация Cloud Shell](https://docs.cloud.google.com/docs/authentication/set-up-adc-cloud-dev-environment).

## 3. Подготовить только Agent Engine

Следующий шаг включает Vertex AI и Storage API и создаёт staging bucket, поэтому выполняется только после решения владельца использовать платные облачные ресурсы:

~~~bash
bash scripts/cloud_shell_agent.sh prepare campuspulse-ai-511817
~~~

Скрипт создаёт bucket gs://campuspulse-ai-511817-agent-staging, если его ещё нет и права позволяют; устанавливает зависимости в отдельную .venv; проверяет реальный MCP и ADC. Он не подключает биллинг, не меняет IAM, не создаёт Firestore/Cloud Run и не разворачивает агента.

Для этого пути используется Python 3.11, совпадающий с sys_version в scripts/deploy_agent.py. В Cloud Shell обычно установлен Python 3.12, поэтому скрипт использует предварительно доступный uv для отдельного Python 3.11. При необходимости uv загрузит нужный интерпретатор. Версии библиотек берутся из requirements.lock; системный Python не заменяется. [Среда Cloud Shell](https://docs.cloud.google.com/shell/docs/how-cloud-shell-works), [управление Python в uv](https://docs.astral.sh/uv/guides/install-python/).

Не запускайте scripts/setup_gcp.sh для этого минимального этапа: существующий скрипт предназначен для более широкой инфраструктуры и дополнительно создаёт базу/учётную запись web-сервиса и меняет IAM.

## 4. Развернуть агента

Это уже реальный потенциально платный запрос Gemini и создание управляемого облачного ресурса:

~~~bash
bash scripts/cloud_shell_agent.sh deploy campuspulse-ai-511817
~~~

Сначала выполняется маленький live-запрос к Vertex Gemini с ADC, затем scripts/deploy_agent.py вызывает именно vertexai.preview.reasoning_engines.ReasoningEngine.create — API, указанный в кейсе. SDK отправляет сериализованного агента, зависимости и пакет campuspulse через staging bucket. Локальный Developer API key не используется вместо Vertex для этой проверки. [ReasoningEngine.create](https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai.preview.reasoning_engines.ReasoningEngine).

Текущий model default — gemini-3.8-flash, endpoint Gemini — global, регион ресурса агента — us-central1. Их доступность в конкретном проекте подтверждает только успешный запрос; строка конфигурации её не гарантирует. При model not found/quota/IAM ошибке сначала устраните её, не объявляйте deployment готовым.

Результат сохраняется в deployment.json с api_verified=false. Это означает «ресурс создан», а не «API уже работает». Если файл уже есть и относится к тому же проекту/региону, helper использует update вместо создания дубликата.

Для новой версии в другой распакованной папке сохраните прежний deployment.json либо явно передайте известное имя ресурса:

~~~bash
.venv/bin/python -m scripts.deploy_agent \
  --project campuspulse-ai-511817 \
  --bucket gs://campuspulse-ai-511817-agent-staging \
  --region us-central1 \
  --update projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID
~~~

PROJECT_NUMBER и ENGINE_ID заменяются значениями реального предыдущего deployment.json, не примерными числами. Путь create/update и версии Python/pinned packages проверены по установленному SDK; живое развёртывание проверяется отдельно. Для ошибок сериализации нужно сопоставить версии Python/cloudpickle, а не обновлять все зависимости случайным образом. [Рекомендации Google по сериализации](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/agent-engine/troubleshooting/deploy?hl=id).

## 5. Проверить настоящий API

~~~bash
bash scripts/cloud_shell_agent.sh verify campuspulse-ai-511817
~~~

Эта команда делает удалённый запрос и поэтому тоже может расходовать квоту/средства. Успех требует фактических выполненных MCP current_time и study_progress в ответе. Только тогда deployment.json получает api_verified=true, а evidence/live-cloud.json — время, resource name и реальный журнал.

При ошибке не создавайте новый ресурс повторно без необходимости: сначала посмотрите причину, доступ runtime service agent и журнал Google. Не выдавайте создание ресурса или локальный контрактный тест за успешный remote query.

Для сохранения результата на ноутбук:

~~~bash
cloudshell download deployment.json evidence/live-cloud.json
~~~

Проверьте содержимое evidence перед отправкой команде. Секреты туда не должны попадать, но название проекта и пользовательские данные других сценариев могут быть личными.

## 6. Интерфейс может пока оставаться локальным

После проверки Agent Engine можно оставить веб-интерфейс на ноутбуке. В локальном .env укажите AGENT_MODE=remote и настоящий ENGINE_RESOURCE_NAME из deployment.json. Для вызова приватного API ноутбуку всё равно нужны ADC с подходящими правами; учётные данные Cloud Shell автоматически на ноутбук не переносятся.

В обычном локальном терминале Google Cloud CLI:

~~~bash
gcloud auth application-default login
gcloud auth application-default set-quota-project campuspulse-ai-511817
~~~

После перезапуска чата журнал должен показывать mode=remote и фактические удалённые вызовы. [ADC для локального компьютера](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).

Для простой локальной проверки функций до GCP владелец может настроить серверный GEMINI_API_KEY из Google AI Studio. Это отдельный Developer API маршрут, а не Agent Engine deployment и не автоматическая замена Vertex в облаке. Ключ хранится только в .env сервера, не передаётся студентам и не включается в архив.

## Cloud Run, Firestore и Calendar — следующий этап

scripts/deploy_web.sh уже описывает приватный Cloud Run с ограничением инстансов и Firestore. Он ожидает подготовленные IAM, web service account и базу; минимальный helper выше их не создаёт. Нельзя считать web deployment завершённым только потому, что Agent Engine отвечает.

Google Calendar OAuth настраивается отдельно: Calendar API, consent screen/test users и OAuth Web application. Для локального запуска redirect URI должен точно совпадать с http://127.0.0.1:8765/api/google/callback. В .env задаются GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET и APP_BASE_URL. Пользователь сам подтверждает доступ к основному календарю. Успех записи подтверждается настоящим ответом и ссылкой Google. [OAuth web flow](https://developers.google.com/identity/protocols/oauth2/web-server), [Calendar events.insert](https://developers.google.com/calendar/api/v3/reference/events/insert).

Для Cloud Run понадобятся HTTPS APP_BASE_URL, COOKIE_SECURE=true и один стабильный GOOGLE_TOKEN_ENCRYPTION_KEY в Secret Manager вместе с OAuth secret. Служебной учётной записи web-сервиса выдаются права только на нужные секреты. Callback URL с code/state не должен попадать в публичные журналы. Refresh/access tokens не передаются Gemini, MCP или браузеру.

Перед заявлением полного результата отдельно проверяются web URL, Firestore persistence, Calendar OAuth/реальное событие и актуальная презентация. Публичный доступ автоматически не включается, а текущая локальная SQLite-база не переносится в Firestore сама.

## Что блокирует завершение

- billingEnabled не true либо состояние недоступно: владелец/администратор проверяет платёжный аккаунт.
- 403 при API/bucket/create/query: отсутствует конкретное разрешение пользователя или runtime service agent.
- Gemini model/quota ошибка: нет доступа к выбранной модели/региону или квоте.
- pickle/runtime ошибка: проверяются Python 3.11 и совпадение pinned зависимостей.
- Создан ресурс, но verify не прошёл: deployment существует, доступный API ещё не подтверждён.
- Локальный UI без ADC не вызывает приватный endpoint: авторизация Cloud Shell не является авторизацией ноутбука.

Подготовка этой инструкции не устраняет перечисленные блокеры и не меняет billing/IAM. Последний проверяемый результат должен находиться в настоящем evidence, а не в обещании скрипта.
