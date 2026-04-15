# Подробное описание решения (Lua Generator + Ollama)

Документ описывает **как устроен baseline**, **какие сценарии он закрывает**, **какие HTTP-запросы доступны**, **формат ответов** и **известные ограничения**. Для установки и команд запуска см. [README.md](README.md).

---

## 1. Назначение

Сервис — **локальный** помощник для генерации **Lua-скриптов** под Low-Code платформу **MWS Octapi**: на вход приходит текст задачи (русский/английский), на выходе — фрагмент Lua с проверкой синтаксиса и простыми доменными правилами. Языковая модель вызывается **только через Ollama** внутри Docker-сети; обращений к OpenAPI/Anthropic и т.п. нет.

---

## 2. Архитектура

| Компонент | Роль |
|-----------|------|
| **Контейнер `ollama`** | Демон Ollama, хранение и запуск LLM (именованный volume в compose: `ollama_data` → на хосте обычно **`localscript_ollama_data`** при проекте `localscript`; см. README / [MEMORY_AND_RUNTIME_CHECKS.md](docs/jury/MEMORY_AND_RUNTIME_CHECKS.md)). |
| **Сервис `ollama-pull`** | Одноразовый контейнер при `docker compose up`: `ollama pull` для `MODEL_NAME` и `FALLBACK_MODEL` в тот же volume; при полном провале pull API не стартует. |
| **Контейнер `api`** | FastAPI-приложение: оркестрация, HTTP API, вызов Ollama по HTTP, `luac`, эвристики. |
| **`docker-compose.yml`** | Связывает сервисы, healthcheck, `depends_on`, volume для моделей, bootstrap pull. |

Код приложения лежит в каталоге `api/`:

| Файл | Назначение |
|------|------------|
| `main.py` | Точка входа FastAPI: `GET /health`, `GET /models`, `GET /ready`, `GET /retrieve/debug`, `POST /generate`, общий `httpx.AsyncClient`. |
| `orchestrator.py` | Вся бизнес-логика: уточнения, сбор промпта, Ollama, извлечение кода, reflexion (второй проход). |
| `prompts.py` | Шаблоны системных промптов, few-shot примеры, промпты для уточнения и reflexion. |
| `retriever.py` | Knowledge retrieval: `knowledge/chunks.jsonl` + при наличии `chunks.official.jsonl` + `docs_snippets.json`, BM25 (Whoosh) + keyword bonus, top‑k. |
| `validator.py` | `luac -p` (Lua 5.5 в образе), hard_errors/warnings/hints, запреты и доменные правила Octapi; reflexion при `syntax_ok=false` после первого прохода. |
| `docs_snippets.json` | Статическая база подсказок по API Low-Code (`wf.vars`, `_utils.array`, и т.д.). |

---

## 3. Поток обработки одного запроса `POST /generate`

Запрос попадает в `run_generate()` в `orchestrator.py`. Дальше по шагам:

### 3.1. Режим правки (edit mode)

Если в тексте `prompt` есть маркер правки (рус.: подстроки в нижнем регистре — **дописать / допиши / доработать / доработай / исправить / исправь / изменить / измени**; англ.: отдельные слова **fix / edit / modify / update** с границами слова) **и** в `context` передан непустой предыдущий код в одном из полей: `previous_code`, `code`, `lua`, `script` — считается, что пользователь хочет **изменить существующий скрипт**. В этом режиме **ветка уточняющего вопроса по короткому запросу не блокирует** генерацию: в промпт добавляется блок с текущим кодом и формулировкой задачи.

### 3.2. Уточнение (`needs_clarification`)

Если **не** edit mode:

- Считается число «слов» (последовательностей непробельных символов) в `prompt`.
- Проверяется наличие **ключевых терминов предметной области** (подстроки в нижнем регистре): `wf.vars`, `initvariables`, `_utils`, `массив`, `array`, `цикл`, `loop`, `lua`, `переменн`, `return`, `скрипт`, `octapi`, `low-code`, `lowcode`, `схем`, `workflow` и т.д. (полный список — в `DOMAIN_KEYWORDS` в `orchestrator.py`).

**Правило:** если в запросе **есть** хотя бы один такой термин — уточнение **не** запрашивается (в том числе для очень коротких фраз вроде «верни wf.vars.userName»).  
Если терминов **нет** и при этом запрос **короче 15 слов** — выполняется **отдельный** вызов модели с промптом вида: пользователь хочет X, задай **один** уточняющий вопрос. Ответ API: `status: needs_clarification`, текст в `clarifying_question`.

### 3.3. Retrieval (lexical RAG)

Корпус: **`knowledge/chunks.jsonl`** (manual / tests) + при наличии **`knowledge/chunks.official.jsonl`** (ingestion из PDF/OpenAPI организаторов) + **`docs_snippets.json`** (legacy baseline). Реестр источников — `knowledge/manifest.json`.  
Запрос пользователя и фрагмент предыдущего кода (если есть) объединяются; по токенам строится **BM25**-поиск (Whoosh, временный индекс на диске в контейнере) по полю «тело чанка» (текст + усиленные ключевые слова). Добавляется **бонус за совпадение `keywords`** с запросом (как раньше). Берётся **top‑k** (`RETRIEVAL_TOP_K`, freeze **4** — см. README); в системный промпт попадают строки с пометкой `[source/kind]`.  
Отладка без LLM: `GET /retrieve/debug?q=...&extra=...`. При `RETRIEVAL_DEBUG=1` в ответе `POST /generate` добавляется поле **`retrieval_debug`** (ранги, score, id). Векторная БД **не** используется.

### 3.4. Сбор промпта для генерации

Куски из `prompts.py`:

- Общий системный шаблон: роль ассистента Octapi, правила (`wf.vars`, `wf.initVariables`, `_utils.array.new()`, запрет `os.execute` / `io.*` / `debug.*`, Lua в среде Octapi / локальная проверка luac, инструкция к краткому плану (зависит от **`GENERATION_COMPACT_PLAN`**, freeze **1**), код **только** в блоке ` ```lua ` … ` ``` `).
- Подставляются **retrieved_snippets** и **few-shot** примеры.
- Пользовательская часть: задача; в edit mode — префикс с предыдущим кодом; прочие поля `context` (кроме зарезервированных имён) сериализуются как «доп. контекст».

### 3.5. Вызов Ollama

- URL: `{OLLAMA_BASE_URL}/api/generate` (по умолчанию `http://ollama:11434`).
- Сначала всегда **`MODEL_NAME`**; **`FALLBACK_MODEL`** только при инфраструктурной ошибке основной (сеть, таймаут, HTTP 5xx/404, невалидный JSON, JSON с полем `error`). Ошибки валидации Lua или отсутствие ```lua **не** переключают модель.
- Параметры: `stream: false`, `options.num_ctx` = `CONTEXT_SIZE` (по умолчанию 4096), `options.num_predict` = `OLLAMA_NUM_PREDICT` (freeze **288**, strict **256** — см. README / `docker-compose.hackathon.yml`).
- Таймаут HTTP read к Ollama: **`OLLAMA_HTTP_TIMEOUT_S`** (в Docker по умолчанию **240** с; см. `orchestrator.py`, `docker-compose.yml`).

Из JSON ответа берётся поле `response` (сырой текст модели).

### 3.6. Извлечение Lua

Функция `extract_lua_block()` ищет код в markdown-ограждениях: ` ```lua `, варианты с пробелами/переносами, обычный ` ``` `, а также обрабатывает **обрезанный** ответ (есть открывающий fence, нет закрывающего). Текст нормализуется с учётом CRLF.

Если код извлечь нельзя — `status: error`, пустой `code`, в `validation` (поле `errors` / `hard_errors`) и `message` — пояснение (проверить pull модели, логи).

### 3.7. Валидация

- **Синтаксис:** запуск `luac -p -` со stdin (в образе **Lua 5.5**, сборка из официального исходника в `Dockerfile`); редкий зазор возможен по отличиям рантайма Octapi от «чистого» Lua.
- Если чистый Lua не проходит, но фрагмент похож на **одно выражение без `return`**, проверяется вариант `return <код>` (как компромисс под Low-Code «последнее выражение»).
- **Структура ответа `validation`:** `hard_errors` (блокируют `syntax_ok` и при необходимости ведут к reflexion), `warnings` (не блокируют успех), `hints` (подсказки, не блокируют), плюс **`errors`** — плоский список `hard + warn + hint` для обратной совместимости.
- **Жёсткие правила:** запреты `os.execute`, расширенный набор `io.*` / `debug.*` / `dofile` / `loadfile` / `loadstring` / динамический `load("...")`; для **`wf.<поле>`** вне `vars` / `initVariables` — **hard** только если поле в **явном denylist** (`WF_SUBFIELD_HARD_DENY` в `validator.py`, напр. опечатка `var`, `execute`, `os`…); иначе **warning** (неизвестное API без полного корпуса доки).
- **Предупреждения:** неизвестные методы `_utils.array.*` кроме `new` / `markAsArray`; `require` с нестроковым аргументом; чтение `wf.vars.<имя>` без инициализации в скрипте.
- **Подсказки:** несколько `return`, код после `return` через `;`, `while true`, `getfenv`/`setfenv`, `require(` в принципе, вызов `array.new` без префикса `_utils.array`.

### 3.8. Repair (одна итерация)

**Reflexion** (второй вызов LLM) запускается, если после первого прохода **`syntax_ok`** ложен (в т.ч. из‑за `hard_errors` от `luac` и доменных правил). **`warnings`** и **`hints`** сами по себе второй проход **не** включают. Максимум **два** вызова Ollama на основной путь (`iterations`: 1 или 2).

### 3.9. Итоговый ответ

- `status`: `success` | `needs_clarification` | `error`.
- `code`: итоговый Lua или пустая строка при ранней ошибке.
- `clarifying_question`: заполнено только при `needs_clarification`.
- `message`: краткая сводка для ошибок (удобно в PowerShell); при успехе обычно пусто.
- `validation`: `syntax_ok`, `hard_errors`, `warnings`, `hints`, `errors` (плоский список для совместимости).
- `iterations`: 1 или 2.
- `used_model`, `fallback_used`, `fallback_reason` — см. раздел 4.5 (основной вызов generate; repair логируется отдельно в логах).

---

## 4. HTTP API

### 4.1. `GET /health`

Проверка живости процесса API. Ответ: `{"ok": true}` (не проверяет Ollama).

### 4.2. `GET /models`

Текущая конфигурация имён моделей из переменных окружения (`MODEL_NAME`, `FALLBACK_MODEL`, `OLLAMA_BASE_URL`) и краткое текстовое описание политики fallback (без запроса к Ollama).

### 4.3. `GET /ready`

Готовность к инференсу: HTTP-доступность Ollama (`OLLAMA_BASE_URL`) и наличие в каталоге Ollama **хотя бы одной** из моделей `MODEL_NAME` / `FALLBACK_MODEL` (по списку `GET /api/tags`).  
Код **200** и JSON с `"ready": true`, если можно вызывать `/generate`; **503**, если Ollama недоступен или обе модели отсутствуют (тело JSON объясняет причину).

### 4.4. `GET /retrieve/debug`

Параметры query: **`q`** (текст запроса), опционально **`extra`** (например предыдущий код). Возвращает JSON как у внутреннего `retrieve_for_generation`: `formatted`, `chunks` (ранг, id, source, kind, score, keyword_hits, text_preview), `query_terms`, `corpus_size`. **Без** вызова Ollama.

### 4.5. `POST /generate`

**Тело (JSON):**

```json
{
  "prompt": "строка, минимум 1 символ",
  "context": null
}
```

или

```json
{
  "prompt": "исправь: нужен последний элемент",
  "context": {
    "previous_code": "return wf.vars.items[1]"
  }
}
```

Поле `context` опционально. Осмысленные ключи:

- `previous_code` / `code` / `lua` / `script` — текст текущего Lua для режима правки.
- Любые другие пары ключ–значение попадут в промпт как дополнительный контекст (если не пусто).

Опционально: **`include_diagnostics`** (boolean). При `true` в ответ добавляется объект **`diagnostics`** (размеры промпта, retrieval, этапы, таймауты) — **без изменения** ветвления оркестратора и **без** второго качества генерации относительно `false`. Сервисный UI «Быстро / Глубоко» переключает только это поле.

**Ответ:** см. раздел 3.9; схема также в README. Дополнительно (если был вызов Ollama): **`used_model`** — какая модель ответила на **основной** запрос generate по полному промпту (до repair); **`fallback_used`** / **`fallback_reason`** — использовался ли запасной вариант из‑за инфраструктурной ошибки основной модели. При `needs_clarification` поля относятся к вызову уточнения. Поля опциональны (`null`), если соответствующего вызова не было.

---

## 5. Какие задачи система «умеет» (ожидаемо)

Формально сервис **не исполняет** Lua на платформе Octapi — он **предлагает текст**, который вы вставляете в сценарий. Качество зависит от модели и формулировки запроса.

Типичные сценарии, под которые заточены промпты и сниппеты:

- Чтение и возврат полей **`wf.vars`**, **`wf.initVariables`**.
- Работа с массивами через **`_utils.array`**, индексация, «последний элемент» (`#arr`).
- Простые циклы и условия в Lua.
- Правка уже выданного кода при передаче `previous_code` и формулировке с маркерами правки (см. раздел 3.1).

Точная семантика API Octapi в baseline **не** подгружена из полного OpenAPI — только выжимка в `docs_snippets.json`; сложные сценарии могут требовать расширения сниппетов или смены промптов.

---

## 6. Переменные окружения

### Сервис `api`

| Переменная | Смысл |
|------------|--------|
| `OLLAMA_BASE_URL` | Базовый URL Ollama (в Docker — `http://ollama:11434`). |
| `MODEL_NAME` / `FALLBACK_MODEL` | Имена тегов моделей в Ollama (совпадают с тем, что подтягивает `ollama-pull`). |
| `CONTEXT_SIZE` | `num_ctx` для инференса. |
| `OLLAMA_NUM_PREDICT` | Максимум токенов ответа; при обрыве markdown увеличивайте осторожно (VRAM). |
| `RETRIEVAL_TOP_K` | Сколько чанков знаний в системный промпт (freeze **4**, см. `docker-compose.yml`). |
| `RETRIEVAL_DEBUG` | `1` / `true` — в ответе `POST /generate` добавляется `retrieval_debug`. |

### Сервис `ollama-pull`

Те же `MODEL_NAME` и `FALLBACK_MODEL` (подстановка из `.env` / дефолты в `docker-compose.yml`), плюс `OLLAMA_HOST=http://ollama:11434` внутри compose.

Сборка образа `api` дополнительно использует `PIP_INDEX_URL` (см. README) для обхода проблем с PyPI.

---

## 7. Недостатки и ограничения (честно)

1. **Зависимость от LLM:** галлюцинации, неверные имена API, игнорирование fence — возможны; repair **один** раз не гарантирует исправление.
2. **Версия Lua:** в контейнере `api` синтаксис проверяется через **`luac` Lua 5.5** (тот же минор, что в материалах хакатона); среда Octapi на стороне платформы может добавлять свои глобалы/песочницу — редкие конструкции могут вести себя иначе в проде.
3. **RAG lexical:** BM25 + ключевые слова по локальному корпусу (`chunks.jsonl` + `docs_snippets.json`); семантических эмбеддингов и полного OpenAPI из `localscript-openapi.zip` нет без отдельного переноса.
4. **Уточнения — эвристика:** порог «15 слов» и список `DOMAIN_KEYWORDS` грубые; возможны ложные уточнения или, наоборот, генерация по размытому запросу.
5. **Безопасность кода:** блокируются лишь явные паттерны (`os.execute`, часть `io`, `debug`); полноценный sandbox анализа нет.
6. **Производительность:** на CPU Ollama отвечает медленно; на GPU нужен отдельный compose-файл и рабочий драйвер.
7. **Контекст запроса к модели:** длинные промпты + большой `num_ctx` увеличивают память; лимиты хакатона по VRAM нужно контролировать отдельно (`nvidia-smi`).
8. **Whoosh** используется для **BM25** в retrieval; **luaparser** в зависимостях пока почти не задействован (место под развитие).
9. **Нет сессий и памяти диалога** на стороне API: каждый `POST /generate` обрабатывается изолированно (историю нужно передавать в `context` вручную).

---

## 8. Профили Docker (freeze vs хакатон)

- **Freeze (разработка и артефакты eval):** базовый `docker-compose.yml` — `OLLAMA_NUM_PREDICT` по умолчанию **288**, `CONTEXT_SIZE` **4096**, `OLLAMA_HTTP_TIMEOUT_S` **240**, у **ollama** — `OLLAMA_NUM_PARALLEL=1`.
- **Строгая проверка хакатона:** `docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build` — **`OLLAMA_NUM_PREDICT=256`**, те же `num_ctx=4096` и таймаут **240** на HTTP-вызов из `api`. См. также `.env.hackathon.example`.

Параметры `num_ctx` / `num_predict` **не захардкожены** в Python-константах: они читаются из env в `api/orchestrator.py` при каждом запуске процесса.

## 9. Связанные файлы

- [README.md](README.md) — установка, Docker, GPU, PyPI, примеры curl/PowerShell.
- [docs/jury/HACKATHON_CHECKLIST.md](docs/jury/HACKATHON_CHECKLIST.md) — команды freeze / strict / eval / `nvidia-smi`.
- [tests/run_eval.py](tests/run_eval.py) — массовая проверка примеров из `tests/test_cases.json`.
- `api/knowledge/` — manifest, `chunks.jsonl`, опционально `chunks.official.jsonl`, `raw/organizers/`; [scripts/ingest_knowledge.py](scripts/ingest_knowledge.py), [scripts/ingest_official.py](scripts/ingest_official.py).

Если нужно углубить продукт (эмбеддинги, строгая схема Octapi, несколько шагов repair, юнит-тесты оркестратора), правки логично начинать с `retriever.py`, `knowledge/chunks.jsonl` и при необходимости `prompts.py`.


---

## 10. Финальные strict-метрики (submission baseline)

Финальные артефакты для сдачи:

- `artifacts/eval_live/heavy_four_strict_after.json`
- `artifacts/eval_live/report_hackathon_strict_after.json`

Итог подтверждённого strict-прогона:

- `total_cases`: 18
- `by_status`: `success=17`, `needs_clarification=1`
- `transport_failed_case_ids`: `[]`
- `success_rate`: `1.0`
- `syntax_ok_rate`: `1.0`
- `fallback_used_count`: `0`
- `clarification_count`: `1` (ожидаемый случай `ambiguous_short`)

Интерфейсная часть при этом остаётся freeze-ready и не влияет на строгие модельные метрики.
