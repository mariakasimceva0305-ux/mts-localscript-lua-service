# Technical summary (jury brief)

Краткое описание **фактического** состояния репозитория под хакатон **LocalScript**. Команды для воспроизведения: **[HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md)**.

Дополнительный аналитический материал для защиты (архитектура, разбор ошибок, retrieval-бенчмарк): **[ARCHITECTURE_AND_BENCHMARK.md](ARCHITECTURE_AND_BENCHMARK.md)**.

### Требования хакатона — статус (честная матрица)

| Требование | Статус | Чем подтверждено | Комментарий / риск |
|------------|--------|------------------|---------------------|
| Локальный инференс (Ollama), без внешних LLM API | **Закрыто** | Код: только `httpx` → `OLLAMA_BASE_URL` в `orchestrator.py`; нет SDK облачных LLM | — |
| `num_ctx=4096` в запросе к Ollama | **Закрыто** | `CONTEXT_SIZE` → `options.num_ctx`; strict override **4096** в `docker-compose.hackathon.yml` | `docker exec lua-gen-api printenv CONTEXT_SIZE` |
| `num_predict=256` в strict-профиле | **Закрыто в конфиге** | `OLLAMA_NUM_PREDICT=256` в `docker-compose.hackathon.yml` | Метрики success/latency при256 — **только** после локального eval |
| `OLLAMA_NUM_PARALLEL=1` | **Закрыто** | `docker-compose.yml` + дубль в `docker-compose.hackathon.yml` | `docker exec ollama printenv OLLAMA_NUM_PARALLEL` |
| HTTP read-timeout к Ollama согласован с документацией | **Закрыто** | Единый дефолт **240 с** в `docker-compose.yml`, strict, `.env.example` | Сравнение 220/260 — см. [EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md) |
| RAG / retrieval без векторной БД | **Закрыто** | Whoosh BM25 + `RETRIEVAL_TOP_K` в `retriever.py` | Выбор k между 3–6 — см. runbook + `run_representative_subset.py` |
| Синтаксис Lua + доменные правила | **Закрыто** | `validator.py`, `luac` **Lua 5.5** в образе (см. `api/Dockerfile`) | — |
| Метрики eval при **strict** | **Закрыто** | `artifacts/eval_live/heavy_four_strict_after.json`, `artifacts/eval_live/report_hackathon_strict_after.json` | heavy_four 4/4 success; full strict: success=17, needs_clarification=1, transport_failed_case_ids=[] |
| Укладка в ≤ 8 ГБ VRAM, без CPU offload | **Требует ручной проверки** | Не в CI | `nvidia-smi`, чеклист GPU |
| Соответствие минорной версии Lua целевой Octapi | **Закрыто по версии `luac`** | **Lua 5.5.0** из официального tarball lua.org; доменные правила в `validator.py` | Зазор только по песочнице/глобалам платформы, не по парсеру 5.5 |

---

## 1. Что делает система

Сервис **`api`** (FastAPI) принимает **`POST /generate`**: текст задачи и опциональный **`context`**. Возвращает статус, фрагмент **Lua**, **`validation`** (`luac` + доменные правила), метаданные модели и reflexion. Внешние облачные LLM **не** используются — только **Ollama** по HTTP.

---

## 2. Где задаются параметры инференса (факты из кода)

| Параметр | Источник истины |
|----------|-----------------|
| `num_ctx` | `CONTEXT_SIZE` в **`api/orchestrator.py`** → `options.num_ctx` в теле `POST {OLLAMA_BASE_URL}/api/generate`. Дефолт в коде **4096**, в compose подставляется из env. |
| `num_predict` | `OLLAMA_NUM_PREDICT` в **`api/orchestrator.py`** → `options.num_predict`. Дефолт в коде **320**, если env не задан (в Docker задаётся compose). |
| HTTP read-timeout к Ollama | `OLLAMA_HTTP_TIMEOUT_S` → `httpx.Timeout` в **`api/orchestrator.py`** (дефолт в коде **120** с; в Docker — из compose). |
| `stream` | Всегда **`false`** в **`_ollama_generate`**. |
| Batch (клиентский) | Один запрос FastAPI → один вызов Ollama; отдельного поля «batch» в payload нет. |
| Parallel (сервер Ollama) | Переменная окружения **`OLLAMA_NUM_PARALLEL`** на сервисе **ollama** в **`docker-compose.yml`** (дефолт **1**). Дублируется в **`docker-compose.hackathon.yml`**. |

Файлы: **`api/orchestrator.py`** (строки с `CONTEXT_SIZE`, `NUM_PREDICT`, `payload` и `GENERATE_TIMEOUT`), **`docker-compose.yml`**, **`docker-compose.hackathon.yml`**.

---

## 3. Два профиля конфигурации

| Профиль | Как запустить | `OLLAMA_NUM_PREDICT` | `CONTEXT_SIZE` | `OLLAMA_HTTP_TIMEOUT_S` | Примечание |
|---------|---------------|----------------------|------------------|-------------------------|------------|
| **Freeze** | `docker compose up --build` | **288** | **4096** | **240** (единый дефолт репозитория) | Закоммиченные `artifacts/*.json` сняты при **220** в `diagnostics` — см. файлы. |
| **Строгий хакатон** | `docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build` | **256** | **4096** | **240** | Отдельный override **без** изменения базового freeze-дефолта `288` в первом файле. |

GPU: добавить **`-f docker-compose.gpu.yml`** (см. README).

---

## 4. Lua в контейнере `api` (версия)

- **Факт:** локальная проверка синтаксиса — **`luac` Lua 5.5.0**, собранный при **`docker build`** из официального **`lua-5.5.0.tar.gz`** с проверкой **SHA256** с [lua.org/download.html](https://www.lua.org/download.html) (`make linux`, `INSTALL_TOP=/usr/local`). Пакет **`lua5.5` из apt** в **bookworm** не используется — так воспроизводимо на фиксированном базовом образе **python:3.11-slim-bookworm**.
- **`validator.py`:** порядок поиска бинарника — `LUAC_BIN` → `luac5.5` → `luac` → `luac5.3` (последнее для dev-хостов).
- **Воспроизводимость:** версия tarball задаётся **ARG `LUA_VERSION` / `LUA_SHA256`** в **`api/Dockerfile`**; смена патча Lua — один коммит с обновлением checksum с официальной страницы.

---

## 5. GPU / VRAM / CPU offload

- **Факт:** **`docker-compose.gpu.yml`** пробрасывает **`gpus: all`** только в сервис **ollama**.
- **Не подтверждено** в CI/среде разработки: укладка в **≤ 8 ГБ VRAM** и отсутствие **CPU offload** для конкретной версии Ollama и драйвера.
- **Жюри / участник:** **[HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md)** (`nvidia-smi`, пик `memory.used`, логи `ollama`).

---

## 6. Итоговые параметры: `RETRIEVAL_TOP_K`, timeout, «Быстро / Глубоко»

### 6.1 `RETRIEVAL_TOP_K`

- **Зафиксировано в репозитории:** **`4`** (`docker-compose.yml`, `.env.example`, документация).
- **Сравнение 3 / 4 / 5 / 6** в этой среде **не выполнялось** (нет поднятого Ollama в CI). Методика и таблица для локального заполнения: **[EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md)**, скрипт **`tests/run_representative_subset.py`**.
- **Логика без «вкуса»:** выбрать k по **минимуму transport-fail**, затем по **success/syntax_ok** на 7 generation-кейсах подмножества, затем по **латентности / длине промпта** (`avg_gen1_prompt_chars` в отчёте). Если локальный sweep даст устойчивый выигрыш **k=5** без регрессий — обновить compose одним коммитом; до тех пор **4** остаётся базой.

### 6.2 `OLLAMA_HTTP_TIMEOUT_S`

- **Итоговое значение: `240` с** — во всех профилях в compose и `.env.example`.
- **220:** в закоммиченных артефактах eval встречались **`ReadTimeout`** на длинных путях; годится для экспериментов, не как единый дефолт.
- **260:** не показал бы улучшения **качества** генерации (таймаут только на транспорт); удлиняет ожидание при сбоях. **Не вводим** без данных runbook.

### 6.3 Режимы «Быстро / Глубоко» (сервисный UI)

- **Факт из кода:** переключается только флаг **`include_diagnostics`** в `POST /generate` (`api/main.py`). Оркестратор **не** меняет промпты, retrieval, число итераций или модель в зависимости от этого флага.
- **Смысл для пользователя:** **Быстро** — компактный JSON ответ; **Глубоко** — тот же результат плюс **`diagnostics`** (размеры промпта, retrieval, этапы) для разбора жюри и логов.
- **Честная формулировка:** разница **не косметическая** для отладки (поле есть/нет), но **не** «другая глубина рассуждения модели». Менять поведение модели отдельным флагом = новая фича вне текущего scope.

---

## 7. Риск «подгонки» под публичные тесты

- В **`validator.py`** **нет** ветвлений по `id` кейсов.
- В корпусе **`knowledge/chunks.jsonl`** есть обобщающий чанк про паттерны из `tests/test_cases.json` (не привязан к id); это влияние retrieval на формулировки, а не хардкод валидатора. Удаление не выполнялось (вне запроса на урезание RAG).

---

## 8. Артефакты eval в репозитории

- **Финальные (submission):**
  - `artifacts/eval_live/heavy_four_strict_after.json` -> **4/4 success**
  - `artifacts/eval_live/report_hackathon_strict_after.json` -> **18 cases, success=17, needs_clarification=1, transport_failed_case_ids=[]**
- **Исторические (сохранены для сравнения):**
  - `artifacts/eval_live/heavy_four_after.json`
  - `artifacts/eval_live/report_freeze_2026-04-13.json`

---

## 9. Strict-профиль: что подтверждено статически, что — только прогоном

| Проверка | Статус |
|----------|--------|
| В **`docker-compose.hackathon.yml`** заданы `CONTEXT_SIZE=4096`, `OLLAMA_NUM_PREDICT=256`, `OLLAMA_HTTP_TIMEOUT_S=240`; у **ollama** — `OLLAMA_NUM_PARALLEL=1` | **Подтверждено** ревью файлов и `docker compose … config` (слияние с базовым `docker-compose.yml`) |
| Значения реально в процессе `api` / `ollama` | **Ручная проверка:** `docker exec … printenv` (см. чеклист) |
| Heavy four / полный eval при strict | **Подтверждено артефактами:** `heavy_four_strict_after.json`, `report_hackathon_strict_after.json` |
| Сравнение top_k / timeout | **Ручная проверка:** [EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md) |

---

## 10. Изменённые файлы (финальный техблок)

- `api/Dockerfile` — **Lua 5.5.0** из официального tarball + SHA256; удалён apt **`lua5.3`**.
- `api/validator.py`, `api/prompts.py` — `luac` 5.5, порядок бинарников.
- `docs/jury/TECHNICAL_SUMMARY.md` — матрица требований, Lua, top_k, timeout, Быстро/Глубоко.
- `docs/jury/OPERATIONS_AND_SCALING.md` — эксплуатация и масштабирование.
- `docs/jury/EMPIRICAL_RUNBOOK.md` — план прогонов top_k и timeout, таблицы.
- `docs/jury/HACKATHON_CHECKLIST.md` — проверка env strict, подмножество кейсов.
- `docs/jury/PRESENTATION.md` — версия Lua в контейнере.
- `tests/run_representative_subset.py` — скрипт репрезентативного подмножества.
- `tests/test_validator.py`, `tests/test_cases.json` — формулировки под Lua 5.5.
- `README.md`, `INFO.md` — валидация Lua 5.5, ссылки.

---

## 11. Как честно говорить жюри

- **Закрыто кодом и конфигом:** локальный Ollama, RAG (BM25), **`luac` Lua 5.5** в образе, reflexion, два профиля (**288** freeze vs **256** strict), `num_ctx=4096`, `OLLAMA_NUM_PARALLEL=1`, HTTP-timeout **240 с**, `RETRIEVAL_TOP_K=4` как задокументированный freeze.
- **Частично / руками:** метрики eval строго при **256**; sweep top_k 3–6; железо VRAM и offload.
- **Быстро/Глубоко:** только диагностика в ответе, не «другая модель».

Подробная спецификация API — **`INFO.md`** и **`README.md`** (приоритет у них и у кода).

---

## 12. Закрыта ли «внутренняя часть» и какие риски остались

- **Считать закрытой по дизайну и документации:** да — конфиги strict/freeze согласованы, пути проверки описаны, нет скрытых облачных LLM, валидатор и оркестратор предсказуемы.
- **Реальные остаточные риски:** (1) недетерминизм модели и нагрузки на другом железе; (2) отличия **рантайма Octapi** от «голого» Lua 5.5 (глобалы, песочница); (3) VRAM/offload только на целевой машине; (4) смена **top_k** без заполненного runbook — остаётся дефолт **4**; (5) сборка образа зависит от доступности lua.org и неизменности checksum (при смене файла на зеркале — обновить `LUA_SHA256`).
