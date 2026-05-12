# Backend — FastAPI

Python API-сервер: REST, WebSocket, LLM-оркестрация, MCP, планировщик, семантический кеш.

## Содержание

1. [Локальный запуск](#локальный-запуск)
2. [API](#api)
3. [Движок расписания](#движок-расписания)
4. [Chat Orchestrator](#chat-orchestrator)
5. [LLM-провайдеры](#llm-провайдеры)
6. [Семантический кеш (Exemplar Replay)](#семантический-кеш-exemplar-replay)
7. [Injection Guard](#injection-guard)
8. [MCP-сервер](#mcp-сервер)
9. [База данных](#база-данных)
10. [Переменные окружения](#переменные-окружения)
11. [Тесты](#тесты)
12. [Деплой](#деплой)
13. [Troubleshooting](#troubleshooting)

---

## Локальный запуск

### Без Docker

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux / macOS
pip install -r requirements.txt
set LLM_PROVIDER=mock         # или openai / gemini / yandex / gigachat
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Swagger: http://localhost:8000/docs

### Docker (с live-reload)

```bash
docker compose up --build -d backend
docker compose logs -f backend
```

Контейнер подключает `backend/` как bind-mount — изменения в `app/` применяются без пересборки.

---

## API

| Метод | Путь | Назначение |
|-------|------|-----------|
| GET | `/health` | Health check (`{"ok": true}`) |
| GET | `/tasks` | Текущий план + revision |
| PATCH | `/tasks/{id}` | Обновить задачу (name, assignee, duration, start_date, predecessor_ids) |
| POST | `/tasks` | Добавить задачу через UI (без LLM) |
| DELETE | `/tasks/{id}` | Удалить задачу через UI |
| POST | `/upload` | Multipart `.xlsx` → новый план |
| GET | `/export` | Скачать план как `.xlsx` |
| POST | `/chat` | `{"message": "..."}` → LLM → commands → обновлённый план |
| POST | `/undo` | Откат последней чат-операции |
| POST | `/reset` | Сбросить к seed-плану |
| WS | `/ws` | Real-time: `{"type":"plan_updated", "revision":N, "plan":{...}}` |
| — | `/mcp` | MCP streamable-http (для внешних агентов) |

### Формат ответа `/chat`

```json
{
  "summary": "Перенёс QA на 3 дня позже.",
  "plan": { "tasks": [...], "project_start": "2025-01-01" },
  "revision": 5,
  "clarify": null,
  "meta": {
    "applied": 1,
    "ops": ["move_task"],
    "plan_changed": true,
    "provenance": "llm"
  }
}
```

`provenance`: `llm` — свежий ответ LLM, `replay` — из семантического кеша, `repair` — после repair-retry, `guard` — заблокировано injection guard.

### Формат ошибок

```json
{"error": "error_code", "detail": "Human-readable description"}
```

| Код | HTTP | Описание |
|-----|------|----------|
| `task_not_found` | 404 | Задача с указанным id не найдена |
| `scheduler_invalid` | 400 | Цикл в зависимостях или недопустимая операция |
| `llm_unavailable` | 502 | LLM-провайдер не ответил |
| `llm_timeout` | 504 | LLM не ответил за `LLM_REQUEST_TIMEOUT_SECONDS` |
| `occ_conflict` | 409 | План изменился конкурентно, повторите запрос |
| `chat_turn_limit_reached` | 429 | Превышен лимит чат-запросов за сессию |

---

## Движок расписания

Все мутации **иммутабельны** — `apply_command(plan, cmd)` возвращает новый `ProjectPlan`. Граф зависимостей строится на `networkx.DiGraph`.

| Команда | Поведение |
|---------|-----------|
| `move_task` | Сдвигает `start_date`/`end_date` на `delta_days`, затем `propagate_constraints` |
| `resize_task` | Изменяет `duration_days` (min 1), пересчитывает `end_date`, `propagate_constraints` |
| `swap_tasks` | Обменивает `start_date` двух задач; с `swap_dependencies=true` — ещё и зависимости с полным `full_recompute` |
| `add_task` | Присваивает sequential id (t7, t8…), `full_recompute` от topological sort |
| `delete_task` | Удаляет задачу + чистит ссылки в predecessor_ids, `full_recompute` |
| `set_dependency` | Заменяет predecessor_ids, `assert_acyclic`, `full_recompute`. Группы `SetDependency` применяются атомарно (transient cycles safe) |
| `rename_task` | Меняет имя и/или описание, без пересчёта дат |
| `reassign_task` | Меняет исполнителя, без пересчёта дат |

**`full_recompute`** — сбрасывает все даты и вычисляет заново через topological sort + `project_start`.

**`propagate_constraints`** — только сдвигает задачи вперёд, если `start_date < predecessor.end_date + 1`. Не сбрасывает независимые задачи.

### Аналитика

Модуль `core/analytics.py` предоставляет:
- **Critical path** — `dag_longest_path` (networkx)
- **Parallel groups** — задачи с пересекающимися интервалами без зависимостей
- **Overloaded assignees** — исполнители с перекрывающимися задачами

---

## Chat Orchestrator

`services/chat_orchestrator.py` — центральный модуль обработки чат-запроса.

### Цикл OCC (Optimistic Concurrency Control)

```
snapshot (plan + revision)    ← вне lock
    ↓
compute (injection → cache → LLM → guards → apply_batch)    ← вне lock
    ↓
commit (проверить revision, set_plan, broadcast)    ← под lock
    ↓ конфликт?
retry (до 2 попыток)
```

### Этапы compute

1. **Injection guard** — regex-проверка → block или ok
2. **Embedding** — `maybe_embed(normalized_message | plan_signature)`
3. **Exemplar search** — поиск по `plan_signature`, ранжирование по cosine similarity
4. **Replay / LLM** — exact match → replay; similarity ≥ threshold + grounding → replay; иначе → LLM
5. **Batch guards** — лимит команд, mass-delete guard
6. **apply_batch** → engine → scheduler
7. **Repair** — при `UnknownReferenceError` → повторный LLM-запрос с описанием ошибки

### Few-shot prompting

Даже при cache miss, top-3 найденных exemplar'а передаются LLM как few-shot suffix — повышая качество ответов для похожих запросов.

---

## LLM-провайдеры

Все провайдеры реализуют протокол `LLMClient` с единственным методом `generate_command_batch`.

| `LLM_PROVIDER` | Модель (по умолч.) | SDK/Transport | Structured output |
|-----------------|-------------------|---------------|-------------------|
| `openai` | `gpt-4o-mini` | `openai` SDK (async) | `response_format=CommandBatch` (native) |
| `gemini` | `gemini-1.5-flash` | `google.genai` | `response_mime_type=application/json` + lenient parse |
| `yandex` | `yandexgpt/latest` | `httpx` REST API | Lenient JSON extraction |
| `gigachat` | `GigaChat` | `httpx` + OAuth (Sber) | Lenient JSON extraction |
| `mock` | — | Regex-парсинг | Детерминистический, без API |

### Lenient JSON parsing

`ai/json_llm.py` — извлечение JSON из ответов, которые могут быть обёрнуты в markdown-блоки или содержать trailing text. Поддерживает все LLM-провайдеры кроме OpenAI (у него нативный structured output).

### Multi-turn контекст

Последние 8 пар (user, assistant) хранятся в `SessionState._history`. При вызове LLM:
- OpenAI / GigaChat: передаются как отдельные `user`/`assistant` messages
- YandexGPT: передаются в формате Yandex (поле `text` вместо `content`)
- Gemini: конкатенируются в один текстовый prompt
- Только текущий ход содержит plan JSON → экономия токенов

---

## Семантический кеш (Exemplar Replay)

### Как работает

1. **Нормализация** — `normalize_user_message`: lowercase, collapse whitespace
2. **Топологическая сигнатура** — SHA-256 от `[id, duration_days, predecessor_ids, name]` по всем задачам (без дат, без assignee). Одинаковая структура плана → одинаковая сигнатура
3. **Embedding** — `OpenAIEmbedder` (`text-embedding-3-small`) при наличии `OPENAI_API_KEY`, иначе `HashBagEmbedder` (256-dim, bag-of-words через SHA-256)
4. **Поиск** — `exemplar_repo.search_exemplars`: фильтр по `plan_signature`, top-80 по дате, ранжирование cosine similarity
5. **Replay decision**:
   - Exact match (normalized message + plan_signature) → replay
   - Similarity ≥ threshold + grounding → replay
   - Иначе → LLM
6. **Grounding** — `template_grounded_in_user_message`: все имена задач из шаблона должны быть подстрокой нормализованного сообщения. Предотвращает ложные воспроизведения (например, «перенеси Frontend» не применит шаблон для «перенеси Backend»)

### Шаблоны команд

Хранятся с `task_ref` (имя задачи) вместо `task_id` — переносимы между планами с одинаковой топологией. `template_to_command_batch` при replay резолвит имена обратно в id.

### Пороги

| Параметр | По умолч. | Описание |
|----------|-----------|----------|
| `REPLAY_SIMILARITY_THRESHOLD` | `0.95` | Порог для dense embeddings (OpenAI) |
| `REPLAY_SIMILARITY_THRESHOLD_HASH` | `0.92` | Порог для hash embeddings (без API) |
| `EXEMPLAR_SEARCH_LIMIT` | `5` | Максимум кандидатов из БД |

### Хранение

Таблица `exemplars` в PostgreSQL: `chat_turn_id`, `user_message_norm`, `plan_signature`, `command_template` (JSONB), `embedding` (ARRAY float), `schema_version`. Без PostgreSQL кеш не работает (нет in-memory fallback для exemplar'ов).

---

## Injection Guard

`ai/injection.py` — pre-LLM фильтр на regex-паттернах:

- `ignore (all)? previous (instructions|rules|prompts)` (EN)
- `забудь (все)? предыдущие (инструкции|правила)` (RU)
- `reveal (your)? (system)? prompt` / `покажи (свой)? (системный)? промпт`
- `disregard (all)? (prior|previous|above)`

При срабатывании возвращается `Clarify` с предупреждением, LLM не вызывается.

---

## MCP-сервер

`mcp_server.py` — FastMCP, смонтирован на `/mcp` как ASGI sub-app. Поддерживает `streamable_http_app` (новый SDK) и fallback на `sse_app` (старый SDK).

Каждый tool-вызов:
1. Захватывает `session.lock`
2. Вызывает `apply_command` (тот же движок, что и chat)
3. `persist_current_plan` → сохраняет в PG
4. `broadcast_plan` → WebSocket

---

## База данных

PostgreSQL 16 (опциональный). Три таблицы:

| Таблица | Назначение |
|---------|-----------|
| `plan_versions` | Снимки плана после каждого изменения (source: `chat` / `mcp` / `upload` / `patch`) |
| `chat_turns` | Аудит чат-запросов: user message, summary, latency, provenance, revision_before/after |
| `exemplars` | Семантический кеш: embedding, command template, plan signature |

### Миграции

Alembic (`backend/alembic/`). При `RUN_MIGRATIONS_ON_START=true` (по умолчанию) — автоматический запуск при старте API.

### Без PostgreSQL

Приложение полностью работает с `DATABASE_URL=` (пустая строка). Persistence, chat audit и exemplar replay отключаются; данные живут в памяти.

---

## Переменные окружения

Полный список — в [../.env.example](../.env.example).

### LLM

| Переменная | По умолч. | Описание |
|------------|-----------|----------|
| `LLM_PROVIDER` | `openai` | `openai` · `gemini` · `yandex` · `gigachat` · `mock` |
| `LLM_MODEL` | зависит от провайдера | ID модели |
| `OPENAI_API_KEY` | — | Ключ OpenAI (также включает embeddings для Exemplar Replay) |
| `GEMINI_API_KEY` | — | Ключ Google AI Studio |
| `YANDEX_API_KEY` | — | Api-Key Yandex Cloud |
| `YANDEX_FOLDER_ID` | — | ID папки Yandex Cloud |
| `YANDEX_MODEL_URI` | auto-built | Полный URI модели (`gpt://<folder>/yandexgpt/latest`) |
| `GIGACHAT_CLIENT_ID` | — | Client ID (Sber) |
| `GIGACHAT_CLIENT_SECRET` | — | Client secret (Sber) |

### Лимиты и защита

| Переменная | По умолч. | Описание |
|------------|-----------|----------|
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Таймаут LLM-вызова; при превышении → 504 |
| `MAX_TASKS_TOTAL` | `200` | Лимит задач в плане |
| `MAX_COMMANDS_PER_BATCH` | `50` | Лимит команд в одном LLM-батче |
| `MAX_DELETES_PER_BATCH` | `200` | Порог массового удаления (без подтверждения) |
| `MAX_CHAT_TURNS_PER_SESSION` | `50` | Лимит чат-запросов за сессию |

### Семантический кеш

| Переменная | По умолч. | Описание |
|------------|-----------|----------|
| `REPLAY_SIMILARITY_THRESHOLD` | `0.95` | Порог replay для dense embeddings |
| `REPLAY_SIMILARITY_THRESHOLD_HASH` | `0.92` | Порог replay для hash embeddings |
| `EXEMPLAR_SEARCH_LIMIT` | `5` | Макс. кандидатов exemplar |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Модель эмбеддингов OpenAI |

### Инфраструктура

| Переменная | По умолч. | Описание |
|------------|-----------|----------|
| `DATABASE_URL` | — | `postgresql+asyncpg://...` (пустой = in-memory) |
| `RUN_MIGRATIONS_ON_START` | `true` | Запускать Alembic при старте |
| `CORS_ORIGIN` | `http://localhost:5173` | Разрешённые origins (через запятую) |

---

## Тесты

```bash
cd backend
python -m pytest -q
```

128 тестов: unit-тесты движка и планировщика, интеграционные тесты API, тесты injection guard, тесты аналитики, тесты command template.

### E2E (Playwright)

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

Требуется запущенный backend (`:8000`) с `LLM_PROVIDER=mock`.

---

## Деплой

### Render

- `render.yaml` — Infrastructure as Code (backend + PostgreSQL)
- Docker build: `backend/Dockerfile`, context: `backend`
- Задать `CORS_ORIGIN` (URL фронтенда), `LLM_PROVIDER`, ключи API
- Render автоматически конвертирует `DATABASE_URL` (validator в `config.py` подставляет `+asyncpg`)
- WebSocket поддерживается Render Web Services

---

## Troubleshooting

| Проблема | Решение |
|----------|---------|
| `meta.plan_changed=false` | LLM сгенерировал валидные команды, но `propagate_constraints` вернул даты на место. Попробовать `swap_tasks` или `add_task` |
| `meta.reason=clarify_only` | Модель не поняла запрос. Переформулировать точнее |
| `meta.provenance=replay` неожидан | Кеш сработал. Если нежелательно — изменить план или переформулировать |
| Chart не обновляется | Проверить WebSocket (revision должен быть ≥ текущего) |
| 502 `llm_unavailable` | LLM-провайдер недоступен. Проверить ключи и доступность API |
| 504 `llm_timeout` | LLM не ответил за `LLM_REQUEST_TIMEOUT_SECONDS`. Увеличить таймаут или сменить модель |
| 409 `occ_conflict` | Конкурентная правка. Повторить запрос |

## Структура проекта

```
backend/
├── app/
│   ├── main.py                # FastAPI app factory, CORS, MCP mount, lifespan
│   ├── config.py              # Pydantic Settings из .env
│   ├── api/
│   │   ├── tasks.py           # GET/PATCH/POST/DELETE /tasks, POST /upload, GET /export
│   │   ├── chat.py            # POST /chat
│   │   └── ws.py              # WebSocket /ws
│   ├── ai/
│   │   ├── prompt.py          # SYSTEM_PROMPT + JSON_OUTPUT_SUFFIX
│   │   ├── json_llm.py        # Lenient JSON extraction / CommandBatch parsing
│   │   ├── llm.py             # LLMClient protocol + 5 реализаций
│   │   ├── embeddings.py      # OpenAIEmbedder / HashBagEmbedder
│   │   └── injection.py       # Pre-LLM regex injection guard
│   ├── core/
│   │   ├── models.py          # Task, ProjectPlan (Pydantic)
│   │   ├── commands.py        # Command union (10 типов) + CommandBatch
│   │   ├── engine.py          # apply_command / apply_batch / mock_command_batch
│   │   ├── scheduler.py       # NetworkX: acyclicity, topo sort, propagate, validate
│   │   ├── command_template.py # CommandBatch ↔ template (task_ref вместо id)
│   │   ├── plan_signature.py  # SHA-256 топологическая сигнатура
│   │   ├── analytics.py       # Critical path, parallel groups, overloaded assignees
│   │   ├── state.py           # SessionState (in-memory plan, revision, history, WS)
│   │   ├── seed.py            # 6-task demo plan
│   │   └── excel.py           # parse_excel_bytes / plan_to_excel_bytes
│   ├── db/
│   │   ├── session.py         # AsyncEngine + async session factory
│   │   └── models.py          # SQLAlchemy models (PlanVersionRow, ChatTurnRow, ExemplarRow)
│   ├── repositories/
│   │   ├── chat_repo.py       # save_chat_turn
│   │   ├── exemplar_repo.py   # search_exemplars / insert_exemplar
│   │   └── plan_repo.py       # save_plan_version
│   ├── services/
│   │   ├── chat_orchestrator.py  # OCC + injection + cache + LLM + guards
│   │   └── plan_service.py       # persist_current_plan
│   └── mcp_server.py          # FastMCP tools → engine
├── alembic/                   # Database migrations
├── tests/                     # 128 pytest tests
├── Dockerfile
└── requirements.txt
```
