# Google-подключения · v0.3

Облако отложено владельцем. Этот файл — инструкция; наличие кода/конфигурации не подтверждает развёртывание. Здесь не предлагается вводить API-ключ в браузер студента.

## 1. Gemini без API-ключа

Владелец настраивает Google Cloud project, биллинг, Vertex AI API и IAM. Локальная авторизация для разработки:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project YOUR_PROJECT_ID
```

В `.env` задайте `GOOGLE_CLOUD_PROJECT` и `AGENT_MODE=gemini`. Используется Google Gen AI SDK `Client(vertexai=True, project=..., location=...)` с ADC. На Cloud Run/Agent Engine используются служебные аккаунты, без файловых ключей. `python -m scripts.preflight --live` выполняет небольшой **потенциально платный** запрос; запускать после подключения облака.

При `AGENT_MODE=auto` приложение выбирает `remote`, если задан Engine resource, иначе `gemini` при наличии project+ADC; без них — явный режим `tools`. Обнаруженные credentials не доказывают доступ к модели, его подтверждает только успешный запрос. Ошибка Gemini не скрывается переходом на другой ИИ.

## 2. Google Calendar: один раз для владельца

Calendar OAuth настраивается отдельно от Vertex AI. Уже выполненный вход в Google в Safari не является OAuth-разрешением для CampusPulse.

1. В своём Google Cloud project включите **Google Calendar API**. Создайте OAuth consent configuration. В режиме тестирования добавьте тестовые Google-аккаунты команды.
2. Создайте **OAuth client → Web application**. Для локального запуска добавьте точный redirect URI `http://127.0.0.1:8765/api/google/callback`. Для Cloud Run используйте HTTPS-адрес приложения с тем же путём.
3. В локальном `.env` заполните `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `APP_BASE_URL`. Файл игнорируется Git. Не отправляйте значения в чат и не помещайте их в репозиторий.
4. Перезапустите приложение, откройте «Моя неделя → Подключить Google Calendar» и самостоятельно разрешите доступ к событиям основного собственного календаря. Приложение запрашивает `calendar.events.owned`. Для широкого внешнего использования Google может потребовать проверку OAuth-приложения; режим тестирования имеет ограничения.
5. Подготовьте событие в чате. До получения полного дня/времени будет уточнение. При успехе должна появиться настоящая ссылка Google Calendar. Проверьте её в своём аккаунте. Проверка записи не выполнялась в этой итерации.

Поток включает state, PKCE, одноразовый callback, обновление и отзыв токенов. Access/refresh tokens шифруются, не отдаются в workspace, не передаются Gemini/MCP и не выводятся в trace. Локальная `.calendar-token-key` создаётся в игнорируемой data/ с правами 0600. Не переносите одну базу без соответствующего ключа; при потере ключа подключите Google заново.

## 3. Agent Engine и Cloud Run

После разрешения владельца подключить облако:

```bash
bash scripts/setup_gcp.sh YOUR_PROJECT_ID
python -m scripts.deploy_agent --project YOUR_PROJECT_ID --bucket gs://YOUR_PROJECT_ID-agent-staging
python -m scripts.verify_cloud
bash scripts/deploy_web.sh YOUR_PROJECT_ID ENGINE_RESOURCE_NAME
```

Используется именно `vertexai.preview.reasoning_engines.ReasoningEngine.create/update`, как в ТЗ. `verify_cloud` требует реальный удалённый ответ с успешными MCP current_time и study_progress, а не только создание ресурса. Результат пишется в локальный `evidence/live-cloud.json`; проверьте личные данные перед публикацией.

Cloud Run по умолчанию приватный. Для OAuth-входа нужен доступный пользователю HTTPS URL, разрешённый IAM-доступ к сервису и соответствующий redirect URI. Публичный доступ автоматически не включается.

Для Calendar на Cloud Run:

- `APP_BASE_URL` — фактический HTTPS URL; `COOKIE_SECURE=true`.
- OAuth client secret и **один стабильный Fernet key** хранятся в Google Secret Manager и подаются как `GOOGLE_OAUTH_CLIENT_SECRET` и `GOOGLE_TOKEN_ENCRYPTION_KEY`.
- `GOOGLE_OAUTH_CLIENT_ID` задаётся серверу. Дайте web service account доступ только к нужным секретам.
- `STORAGE_BACKEND=firestore`; один encryption key на все инстансы/ревизии. Без него Calendar OAuth для Firestore отклоняется до входа.
- Локальные launcher/Dockerfile отключают access-log Uvicorn. На прокси/Cloud Logging исключите URL callback с параметрами `code/state` из сохраняемых request logs. Токены никогда не должны попадать в журналы.
- Контекст Calendar создаётся web-сервисом и передаёт Agent Engine только события/время получения, без OAuth credentials. Запись событий выполняет web-сервис по прямой команде, не модель.

Firestore и Cloud Run ещё не проверены live. Перед финальной сдачей проверить OAuth callback на выбранном домене, сохранность сессии, refresh после истечения access token, отдельные браузеры, event retry и источник занятых интервалов.

## Официальные источники

- [Google Gen AI SDK](https://github.com/googleapis/python-genai)
- [OAuth для web applications](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Google Calendar events.insert](https://developers.google.com/calendar/api/v3/reference/events/insert)
- [Google Calendar events.list](https://developers.google.com/calendar/api/v3/reference/events/list)
- [Gemini OAuth](https://ai.google.dev/gemini-api/docs/oauth)
