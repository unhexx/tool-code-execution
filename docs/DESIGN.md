# Дизайн: tool-code-execution

## Назначение

Локальная замена server-side `code_execution` xAI. Клиентская функция в agentic loop: модель запрашивает вызов, процесс исполняет сниппет в ограниченном интерпретаторе и возвращает stdout/stderr.

Документ смешивания: https://docs.x.ai/developers/tools/advanced-usage#mixing-server-side-and-client-side-tools

## Границы

Входит: короткие вычисления, разбор текста, преобразования структур данных на Python 3.

Не входит: сеть, файловая система, subprocess, нативные расширения, установка пакетов, долгие джобы.

## Архитектура

```
агент  --POST /v1/invoke-->  server.py
                               |- ast.parse
                               |- _Guard (запрет import/dunder/open/eval)
                               |- exec в урезанных builtins
                               \- JSON {ok, stdout, stderr, error}
```

Транспорт: stdlib `ThreadingHTTPServer`, JSON. Без FastAPI.

## Контракт HTTP

| Метод | Путь | Смысл |
|-------|------|--------|
| GET | `/healthz` | liveness |
| GET | `/schema` | function-calling schema для xAI SDK |
| POST | `/v1/invoke` | `{"arguments":{"code":"...","timeout_sec":5}}` |

Авторизация: `Authorization: Bearer $TOOL_TOKEN`.

## Изоляция

- AST-guard до `exec`
- белый список модулей (`math`, `json`, `re`, …)
- контейнер: loopback, `cap_drop: ALL`, `read_only`, tmpfs `/tmp`, `pids_limit`, `mem_limit`
- это не gVisor/Firecracker; усиление изоляции — отдельный пункт задач

## Качества

- детерминированные тесты без сети
- ошибка запрета — структурированный `ok: false`, не 500 на ожидаемом reject
- код сниппета ≤ 40 КБ

## Нефункциональные ограничения

Порт по умолчанию `8091`. Секреты не в git.

