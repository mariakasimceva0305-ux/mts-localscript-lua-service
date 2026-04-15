# LocalScript: эксплуатация и масштабирование

Коротко, для инженера: запуск, обновление данных, проверки, типичные сбои. Без лишней теории.

---

## 1. Два конфигурационных профиля

| Профиль | Команда | Зачем |
|---------|---------|--------|
| **Freeze** | `docker compose up --build` | Разработка, eval-артефакты в репозитории (`num_predict=288` по умолчанию). |
| **Strict (хакатон)** | `docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build` | Проверка условий: `num_predict=256`, `num_ctx=4096`, явный `OLLAMA_NUM_PARALLEL=1` на ollama. |
| **GPU** | Добавить `-f docker-compose.gpu.yml` | Ollama на NVIDIA (см. README). |

Переменные подставляются из `.env` / окружения хоста в YAML. После смены профиля пересоздайте контейнеры (`up --build` или `--force-recreate` для `api`).

### 1b. Имя проекта и volumes (модели не «терять»)

- В **`docker-compose.yml`** задано **`name: localscript`**. Именованные volumes на хосте: **`localscript_ollama_data`**, **`localscript_whoosh_data`**, **`localscript_docs_extract_data`**.
- В **`.env.example`** рекомендуется **`COMPOSE_PROJECT_NAME=localscript`** (приоритет имени: `-p` → эта переменная → `name:` в compose → имя каталога).
- Если запускать из **разных папок без фиксированного имени**, Docker раньше создавал **новый** префикс volume по имени каталога — создавалось ощущение **повторной загрузки моделей**. Сейчас префикс стабилен при стандартном compose из репозитория.
- **`docker compose down -v`** удаляет volumes проекта — следующий **`up`** снова выполнит **`ollama-pull`** на полный объём. Обычный **`docker compose down`** (без `-v`) данные не удаляет.

Подробнее: [MEMORY_AND_RUNTIME_CHECKS.md](MEMORY_AND_RUNTIME_CHECKS.md), скрипты `scripts/compose_diagnostics.*`, `scripts/check_ollama_models.*`.

---

## 2. Здоровье сервиса

| Проверка | Что значит |
|----------|------------|
| `GET /health` | Процесс API жив (Ollama не проверяет). |
| `GET /ready` | Ollama доступен и в каталоге есть хотя бы одна из моделей `MODEL_NAME` / `FALLBACK_MODEL`. |
| `docker compose ps` | `ollama` и `lua-gen-api` — **healthy**. |

Быстрый smoke: см. [HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md), раздел 3.

---

## 3. Обновление моделей

1. Задайте `MODEL_NAME` / `FALLBACK_MODEL` в `.env` или экспорте перед `docker compose`.
2. Пересоберите/перезапустите стек; контейнер **`ollama-pull`** при успешном `depends_on` снова выполнит `pull` в volume `ollama_data`.
3. Либо вручную: `docker exec -it ollama ollama pull <tag>`.

Без успешного pull API не стартует (зависимость от `ollama-pull`).

---

## 4. Обновление корпуса знаний

| Часть | Где | Действие |
|-------|-----|----------|
| Основной корпус | `knowledge/chunks.jsonl` + `knowledge/manifest.json` | Редактирование / генерация чанков; перезапуск `api` пересобирает Whoosh-индекс при работе. |
| Официальные документы | `api/knowledge/raw/organizers/`, `scripts/ingest_official.py` | Ingest → `chunks.official.jsonl` (см. README, опциональные зависимости для PDF). |
| Статические сниппеты | `api/docs_snippets.json` | Правка JSON; пересборка образа или volume-монтирование при dev. |

Проверка корпуса: `python scripts/ingest_knowledge.py --by-source`.

Параметр **`RETRIEVAL_TOP_K`** (env `api`) — сколько чанков попадает в системный промпт; меняется только перезапуском `api` с новым env.

---

## 5. Прогон eval

Зависимости: `pip install -r tests/requirements.txt`.

- Полный набор: `python -u tests/run_eval.py --base-url http://127.0.0.1:8000 --timeout 720 --output … --label …`
- Четыре тяжёлых кейса: `tests/run_heavy_four.py` (см. чеклист).
- Репрезентативное подмножество (для сравнения top_k / timeout): `tests/run_representative_subset.py` (см. [EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md)).

Конфигурация (**RETRIEVAL_TOP_K**, **OLLAMA_NUM_PREDICT**, таймауты) задаётся **на сервере**; клиентские скрипты только дергают HTTP.

---

## 6. Типичные ошибки

| Симптом | Куда смотреть |
|---------|----------------|
| HTTP 503 на `/ready` | Логи `docker compose logs ollama`; pull моделей; `OLLAMA_BASE_URL` в `api`. |
| `ReadTimeout` / долгий ответ | `OLLAMA_HTTP_TIMEOUT_S` (один вызов Ollama; при reflexion — два подряд); нагрузка CPU/GPU; см. `diagnostics` при `include_diagnostics: true`. |
| `syntax_ok: false` стабильно | Логи `api`; промпт и retrieval; не смешивать с инфраструктурным таймаутом (там обычно нет полного JSON ответа). |
| Пустой / битый ответ модели | Обрыв `num_predict`; размер промпта (`num_ctx`); качество модели. |

---

## 7. Масштабирование на «несколько пользователей»

- **Один инстанс `api`** (FastAPI) обычно достаточен для демо и небольшой внутренней нагрузки: узкое место — **очередь Ollama** и **`OLLAMA_NUM_PARALLEL`** (в репозитории **1** — предсказуемая латентность и соответствие хакатону).
- Горизонтально: несколько реплик **`api`** за балансировщиком **не** дадут линейного ускорения без нескольких GPU/инстансов Ollama; каждая реплика всё равно бьёт в один `OLLAMA_BASE_URL`.
- Имеет смысл: отдельный хост/VM с Ollama + один (или несколько) `api`, указывающих на него по сети; корпус и Whoosh — локально в контейнере `api` или общий volume при осторожной синхронизации.

---

## 8. Что менять независимо

| Компонент | Можно менять отдельно |
|-----------|------------------------|
| **Статический фронт** | `api/static/*` — без пересборки моделей; пересборка образа `api` или bind-mount. |
| **API (Python)** | Код в `api/*.py`, Dockerfile `api` — пересборка сервиса `api`. |
| **Ollama** | Образ, модели, GPU — сервис `ollama`; переменные `OLLAMA_*` на нём. |
| **Корпус** | Файлы в `knowledge/`, ingest-скрипты — обычно достаточно перезапуска `api`. |

Оркестратор и валидатор тесно связаны с промптами и Lua — менять согласованно.

---

## 9. Ссылки

- Команды freeze / strict / GPU: [HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md)
- Память (диск/VRAM), volumes, первый/повторный запуск: [MEMORY_AND_RUNTIME_CHECKS.md](MEMORY_AND_RUNTIME_CHECKS.md)
- Итоги по параметрам и требованиям: [TECHNICAL_SUMMARY.md](TECHNICAL_SUMMARY.md)
- Мини-прогоны top_k / timeout: [EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md)
