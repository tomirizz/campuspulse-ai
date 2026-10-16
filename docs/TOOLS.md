# MCP и custom functions

MCP использует официальный Python SDK `mcp`, JSON-RPC по stdio. Agent Core запускает отдельный сервер `python -m campuspulse.mcp_server`, выполняет `initialize`, получает схемы через `list_tools` и вызывает `call_tool`. Никаких HTTP-вызовов вместо MCP под тем же названием нет.

| Tool | Транспорт | Вход | Результат / источник |
|---|---|---|---|
| `current_time` | MCP stdio | IANA timezone | Системное время с UTC offset |
| `github_issues` | MCP stdio | `owner/repository` | Живой GitHub API; до 30 последних записей, PR исключены; URL, fetched_at |
| `list_tasks` | Function Calling | Нет | Задания текущей сессии |
| `plan_week` | Function Calling | Нет | Детерминированный план с рисками по дедлайнам |
| `list_materials` | Function Calling | Нет | ID, имена и число страниц загруженных материалов |
| `read_material` | Function Calling | ID, первая страница | До 3 страниц; только материалы этой сессии |
| `propose_task` | Function Calling | Название, курс, aware deadline, длительность | Предложение, `saved=false`; сохранение через форму |

Схемы MCP превращаются в Gemini `FunctionDeclaration(parameters_json_schema=...)`. Автоматическое выполнение SDK отключено, чтобы приложение контролировало лимиты, allowlist и журнал. Оригинальные Gemini Parts сохраняются в истории текущего цикла: это сохраняет function-call IDs и thought signatures.

Следующий шаг выбирает Gemini на основании tool responses. В публичном журнале показывается только наблюдаемое действие и фактический результат. Части ответа с `thought=True` не выводятся пользователю. После 8 раундов или 12 вызовов цикл прекращается с явным сообщением.

Для автономной работы не нужен доступ модели к оболочке или произвольным URL. Неизвестные инструменты и неверные аргументы отклоняются. Текст PDF/issues считается данными, а не инструкциями. Сервер инструментов не получает ключ Gemini. Любой proposed task требует проверки человеком.

В режиме `tools` маршрутизация фиксированная и явно обозначена в интерфейсе. Этот режим нужен для проверки продукта без оплаты; он не используется как доказательство автономности Gemini.

Официальные источники:

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Google Gen AI SDK](https://googleapis.github.io/python-genai/)
- [ReasoningEngine.create](https://docs.cloud.google.com/python/docs/reference/vertexai/latest/vertexai.preview.reasoning_engines.ReasoningEngine)
