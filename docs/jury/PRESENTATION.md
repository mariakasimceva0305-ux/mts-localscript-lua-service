# Презентация: локальный Lua-генератор для Octapi (markdown-слайды)

Ниже **10 слайдов** в порядке показа. Содержание соответствует **текущему коду** репозитория (Ollama + FastAPI + retrieval + `luac` + reflexion).

---

## Слайд 1 — Заголовок

**Lua для MWS Octapi Low-Code: локальная генерация с проверкой**

- Без облачных LLM API: только **Docker** + **Ollama** на машине жюри.
- Репозиторий: генерация → валидация → при необходимости **второй проход (reflexion)**.

---

## Слайд 2 — Проблема

**Зачем сервис**

- Пользователь формулирует задачу на естественном языке (RU/EN).
- Нужен **короткий Lua-скрипт** под контракт Octapi: `wf.vars`, `wf.initVariables`, `_utils`, …
- Риск: галлюцинации, неверный синтаксис, опасные вызовы — нужна **автоматическая проверка**.

---

## Слайд 3 — Решение в одном предложении

**Локальная «маленькая» модель + знания из корпуса + жёсткая валидация + самопроверка**

- **qwen2.5-coder:7b** (основная), **deepseek-coder:6.7b** (только инфраструктурный fallback).
- Фрагменты документации подмешиваются в промпт (**retrieval**).
- После ответа — **`luac`** и правила платформы.
- Если синтаксис не сошёлся — **reflexion**: второй запрос к модели с полным отчётом валидации.

---

## Слайд 4 — Почему локально

**Приватность и воспроизводимость**

- Данные и модели остаются в контейнерах; нет исходящих вызовов к OpenAI/Anthropic.
- Один старт: `docker compose up --build` (см. README).
- Жюри может повторить **eval** и **heavy_four** с теми же env (freeze в README / `.env.example`).

---

## Слайд 5 — Архитектура (три блока)

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│   ollama    │     │  ollama-pull │     │  api (FastAPI)  │
│   (демон)   │ ←── │  (pull раз)  │ ──→ │  orchestrator   │
└─────────────┘     └──────────────┘     └─────────────────┘
```

- **ollama-pull** гарантирует наличие весов до старта API.
- **api** держит HTTP-клиент к Ollama, RAG, валидатор.

---

## Слайд 6 — Retrieval (без векторной БД)

**Lexical RAG: BM25 + ключевые слова**

- Корпус: `knowledge/chunks.jsonl`, `docs_snippets.json`, опционально official chunks.
- Индекс Whoosh строится при работе; в промпт попадает top‑**k** фрагментов (**`RETRIEVAL_TOP_K=4`** freeze).
- Отладка без LLM: **`GET /retrieve/debug?q=...`**.

---

## Слайд 7 — Валидация

**Не «на глаз», а `luac` + доменные правила**

- Синтаксис Lua 5.5 в контейнере (официальный исходник lua.org, см. `api/Dockerfile`).
- Жёсткие ошибки vs предупреждения (чтение `wf.vars` без init — обычно warning).
- Запреты: `os.execute`, `io.*`, `debug.*`, …

---

## Слайд 8 — Reflexion (второй проход)

**Один дополнительный вызов модели при `syntax_ok=false`**

- Промпт содержит: исходную задачу, код после первого прохода, **hard/warn/hint** от валидатора.
- Та же политика моделей; **не** путать с fallback при сетевой ошибке.
- В ответе API: **`reflexion_applied`**, **`first_pass_syntax_ok`**, **`iterations`** (1 или 2).

---

## Слайд 9 — Fallback моделей (инфраструктура)

**Только при сбое транспорта к Ollama**

- Таймаут, 5xx, обрыв JSON, поле `error` в ответе Ollama → попытка **`FALLBACK_MODEL`**.
- Ошибка «плохой Lua» → **не** переключение модели, а ветка **reflexion** (если применимо по `syntax_ok`).

---

## Слайд 10 — Результаты измерений (freeze)

| Набор | Результат |
|-------|-----------|
| **heavy_four strict** (`artifacts/eval_live/heavy_four_strict_after.json`) | **4/4** success |
| **Полный strict eval** 18 кейсов (`report_hackathon_strict_after.json`) | **17 success + 1 expected needs_clarification (`ambiguous_short`)** |

- `transport_failed_case_ids = []`, `syntax_ok_rate = 1.0`, `fallback_used_count = 0`.

---

## Слайд 11 — Конфигурация freeze (команда жюри)

Ключевые env (см. **README** и **`.env.example`**):

`MODEL_NAME`, `FALLBACK_MODEL`, `RETRIEVAL_TOP_K=4`, `OLLAMA_NUM_PREDICT=288` (freeze) / **`256`** (strict, `docker-compose.hackathon.yml`), `GENERATION_COMPACT_PLAN=1`, `OLLAMA_HTTP_TIMEOUT_S=240`, `OLLAMA_NUM_PARALLEL=1` на **ollama**.

Eval: **`--timeout 720`** на кейс.

---

## Слайд 12 — Заключение

**Итог**

- End-to-end путь: **уточнение → RAG → LLM → Lua → luac → [reflexion]**.
- Полностью **оффлайн** относительно внешних AI SaaS.
- Документация для жюри: **README**, **`docs/jury/TECHNICAL_SUMMARY.md`**, сценарий демо, диаграммы.
