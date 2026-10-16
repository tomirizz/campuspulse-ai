# Облачный запуск

Для этой команды создан проект **campuspulse-ai-511817**. На 16 октября 2026 биллинг не подключён; владелец решил вернуться к облаку позже. Ниже — подготовленная процедура, а не отчёт об успешном развёртывании.

## 1. Действия владельца аккаунта

В [Google Cloud Billing](https://console.cloud.google.com/billing/linkedaccount?project=campuspulse-ai-511817) подключить биллинг к нужному проекту. Платёжные данные, принятие условий Google и лимит бюджета выполняет владелец. Наличие стартовых кредитов зависит от аккаунта; бесплатность работы не гарантируется.

Расходы могут включать Gemini, Agent Engine, Cloud Run, Firestore, Cloud Build, Artifact Registry, Cloud Storage и логи. Перед запуском проверить [текущие цены Google Cloud](https://cloud.google.com/pricing) и установить уведомления о бюджете. Уведомление о бюджете **не является жёстким ограничением расходов**. После демонстрации удалить ненужные ресурсы вручную; не удалять сам проект с данными команды без решения владельца.

## 2. Локальный доступ и проверка модели

Установить [Google Cloud CLI](https://cloud.google.com/sdk/docs/install) из официального источника. В корне репозитория:

```bash
gcloud auth login
gcloud auth application-default login
gcloud auth application-default set-quota-project campuspulse-ai-511817
source .venv/bin/activate
```

Указать `GOOGLE_CLOUD_PROJECT=campuspulse-ai-511817`, `AGENT_MODE=gemini`, `GEMINI_LOCATION=global` и `GEMINI_MODEL=gemini-3.6-flash` в `.env`. Убедиться, что выбран нужный аккаунт, биллинг активен, а аккаунт имеет права создавать сервисы и назначать необходимые роли.

## 3. Инфраструктура

```bash
bash scripts/setup_gcp.sh campuspulse-ai-511817
python -m scripts.preflight --live
```

Скрипт включает API, создаёт staging bucket, Firestore Native и сервисный аккаунт `campuspulse-web`. Выдаёт ему `roles/aiplatform.user` и `roles/datastore.user`, а сервисной идентичности Agent Engine — доступ к Vertex AI. Он не создаёт долгоживущие ключи service account. При ограничениях организации назначения ролей должен выполнить администратор. Сборка Cloud Run также требует стандартных разрешений Cloud Build; скрипт не расширяет их автоматически при ошибке.

## 4. Agent Engine

```bash
python -m scripts.deploy_agent \
  --project campuspulse-ai-511817 \
  --bucket gs://campuspulse-ai-511817-agent-staging
python -m scripts.verify_cloud
```

`deploy_agent.py` вызывает `vertexai.preview.reasoning_engines.ReasoningEngine.create` с Python 3.11, зафиксированными зависимостями и пакетом `campuspulse`. Файл `deployment.json` сохраняет resource name и сначала содержит `api_verified=false`.

`verify_cloud.py` делает настоящий OAuth API-запрос и требует успешных `current_time` и `github_issues` в трассе. Только успешная проверка устанавливает `api_verified=true`. Доказательство сохраняется в игнорируемый Git файлом `evidence/live-cloud.json`. Перед публикацией любых трасс проверить отсутствие личного текста.

При обновлении передать `--update projects/.../locations/.../reasoningEngines/...`, чтобы не создавать второй оплачиваемый ресурс. Если API изменился, свериться с [официальным SDK reference](https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai.preview.reasoning_engines.ReasoningEngine).

## 5. Интерфейс в Cloud Run

Скопировать `resource_name` из `deployment.json`:

```bash
bash scripts/deploy_web.sh campuspulse-ai-511817 \
  projects/PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID
```

Заменить пример полным реальным именем. Frontend использует Firestore, ADC и Agent Engine. `.env`, SQLite и локальные материалы не входят в контейнер. Cloud Run создаётся **приватным**, с масштабированием 0–2 инстанса и до 4 запросов одновременно на инстанс.

Для показа с машины владельца:

```bash
gcloud run services proxy campuspulse-web \
  --project campuspulse-ai-511817 --region us-central1 --port 8080
```

Открыть `http://localhost:8080`. Если браузер не сохраняет Secure cookie через локальный прокси, использовать прямой HTTPS-доступ через настроенную IAM/IAP-авторизацию; не отключать защиту публичного сервиса ради демонстрации. Публичный доступ через `allUsers` не включается автоматически. Для независимого доступа судей нужно выдать им роль Cloud Run Invoker либо отдельно добавить полноценный вход в приложение.

## Критерии успешного запуска

- Модель реально ответила, в журнале нет статуса имитации.
- В Google Cloud есть ресурс Agent Engine; удалённый `:query` вернул ответ с MCP-трассой.
- Cloud Run открывается авторизованному пользователю; изменения сохраняются в Firestore после перезапуска.
- Две браузерные сессии не видят задания друг друга.
- Контрольный документ даёт ответ со страницей; при ошибке внешнего API агент сообщает об ошибке.

До выполнения этих проверок отметки «развёрнуто» и «полностью выполнено ТЗ» не ставить.
