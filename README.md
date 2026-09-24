# tool-code-execution

Restricted Python sandbox. No network, no filesystem, blocked imports. Drop-in client-side replacement for xAI `code_execution`.

Client-side tool for mixing with xAI server-side tools:

https://docs.x.ai/developers/tools/advanced-usage#mixing-server-side-and-client-side-tools

## Local first

Tasks that do not need a third-party network service run entirely in this process.
Bind address is `127.0.0.1` only.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
TOOL_TOKEN=local TOOL_PORT=8091 .venv/bin/python -m code_execution.server
```

```bash
docker compose up -d --build
curl -sS http://127.0.0.1:8091/healthz
curl -sS http://127.0.0.1:8091/schema
curl -sS -H 'Authorization: Bearer local' -H 'Content-Type: application/json' \
  -d '{"arguments":{}}' http://127.0.0.1:8091/v1/invoke
```

## xAI client-side schema

`GET /schema` returns the function-calling descriptor. Register it next to any
server-side tools (`web_search`, `x_search`, `code_execution`, …) you still
want xAI to execute. When the model calls this function, execution pauses and
your loop must `POST /v1/invoke`.

## Security

- `no-new-privileges`, `cap_drop: ALL`, read-only root, tmpfs `/tmp`
- published on loopback only
- bearer `TOOL_TOKEN` (default `local` — change before any non-loopback bind)

Copyright 2026 Evgeniy Chistyakov · https://exception.expert

## Документы для агентов

- [Дизайн](docs/DESIGN.md)
- [Очередь задач](docs/AGENT_TASKS.md)
- [AGENTS.md](AGENTS.md)

