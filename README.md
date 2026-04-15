# LocalScript Lua Generation Service

Локальный сервис генерации **Lua** для сценариев **MWS Octapi (LocalScript)**. Конвейер: уточнение запроса при необходимости → **лексический RAG (BM25 / Whoosh)** → **Ollama** (без внешних LLM API) → извлечение кода → **`luac` (Lua 5.5)** → при ошибке синтаксиса **reflexion** (второй проход). Поставляется с **Docker Compose**, веб-интерфейсом и HTTP API на **FastAPI**.

Подробная архитектура, контракты эндпоинтов и ограничения: [**INFO.md**](INFO.md). Материалы для защиты и чеклисты: [**docs/jury/**](docs/jury/).

---

## Сдача на хакатоне (репозиторий организаторов)

Официальная приёмка решения выполняется **только** в репозитории **GitLab**, выданном платформой (**«Создать репозиторий»** в интерфейсе, вход через **True Tech Arena**). Убедитесь, что к дедлайну в этом репозитории актуальный код и документация.

**Репозиторий сдачи (GitLab):** [git.truetecharena.ru/mariakasimceva/mts-localscript-lua-service](https://git.truetecharena.ru/mariakasimceva/mts-localscript-lua-service/-/tree/main)

Публикация копии на **GitHub** допустима для портфолио или удобства команды, но **не заменяет** GitLab-сдачу. **CI/CD площадки хакатона не используются** — воспроизводимость проверяется локально (рекомендуется Docker).

---

## Возможности

- Генерация и правка Lua под доменные соглашения Octapi (`wf.vars`, `_utils`, запреты опасных вызовов).
- RAG по корпусу `api/knowledge/` и статическим сниппетам; отладка retrieval: `GET /retrieve/debug`.
- Валидация `luac -p`, разбор предупреждений и «жёстких» ошибок в `validator.py`.
- Веб-UI: чат, редактор, валидация (`http://127.0.0.1:8000` после запуска стека).
- Эндпоинты `POST /generate`, `POST /edit`, `POST /validate`, служебные `GET /health`, `/ready`, `/models`.

---

## Требования

| Компонент | Минимум |
|-----------|---------|
| Docker Desktop или Docker Engine | 24.x+, **Compose V2** (плагин **≥ 2.20**) для `depends_on: service_completed_successfully` |
| ОЗУ | Рекомендуется **16 ГБ+** (модели Ollama + контейнеры) |
| Диск | Несколько **ГБ** под образы и volume с моделями |
| Node.js | **18+** на хосте: `npm ci` и `npm run build:vendor` **до** `docker compose up` |

**GPU (NVIDIA)** не обязателен; для ускорения см. `docker-compose.gpu.yml`.

---

## Быстрый старт (Docker)

Клонируйте репозиторий в каталог с **осмысленным именем** (не используйте имя `node_modules`).

```bash
git clone https://github.com/mariakasimceva0305-ux/mts-localscript-lua-service.git localscript-lua-service
cd localscript-lua-service
npm ci
npm run build:vendor
cp .env.example .env
docker compose up --build
```

Первый запуск: сервис **`ollama-pull`** загружает модели (**`qwen2.5-coder:7b`**, **`deepseek-coder:6.7b`**) в именованный volume — это может занять **десятки минут** в зависимости от сети. Повторные запуски с тем же проектом Compose обычно быстрее.

**Windows** (нестабильный pull / TLS к реестру образов):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\compose_up_retry.ps1
```

Имя проекта Compose зафиксировано как **`localscript`** (`name:` в `docker-compose.yml`, см. `.env.example`), чтобы volumes не «плодились» при смене имени папки на диске.

---

## Проверка готовности

После того как контейнер **`lua-gen-api`** в `docker compose ps` перейдёт в **healthy**:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/ready
```

Ожидается `200`, `/ready` с `"ready": true` при доступных моделях. Минимальная проверка генерации:

```bash
curl -sS -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d "{\"prompt\":\"верни значение wf.vars.userName\",\"context\":null}"
```

Ответ: `status: success`, непустой `code`, `validation.syntax_ok: true` для этого примера.

---

## Профиль, совпадающий с параметрами проверки организаторов

Для **`num_ctx=4096`**, **`num_predict=256`**, **`OLLAMA_NUM_PARALLEL=1`**:

```bash
docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build
```

Базовый `docker-compose.yml` задаёт **`OLLAMA_NUM_PREDICT=288`** (freeze разработки); override в `docker-compose.hackathon.yml` не меняет остальную логику приложения.

---

## Оценка на наборе тестов (хост)

Python 3.10+:

```bash
pip install -r tests/requirements.txt
python -u tests/run_eval.py --base-url http://127.0.0.1:8000 --timeout 720 --output artifacts/eval_live/report.json --label local_run
```

«Тяжёлые» четыре кейса:

```bash
python -u tests/run_heavy_four.py --base-url http://127.0.0.1:8000 --timeout 720 --output artifacts/eval_live/heavy_four.json
```

На Windows клиент eval использует `trust_env=False`, чтобы системный прокси не перенаправлял запросы к `127.0.0.1`.

---

## Сборка образа `api` при ошибках TLS к PyPI

Сеть / прокси / антивирус могут обрывать `pip` внутри `docker build`. Варианты:

1. **Локальные wheels:** `powershell -ExecutionPolicy Bypass -File .\scripts\download_wheels.ps1`, затем `docker compose build api`.
2. **Зеркало индекса:** в `.env` задать `PIP_INDEX_URL` (см. комментарии в `.env.example`).

---

## Ключевые переменные окружения (`api`)

| Переменная | Назначение (кратко) |
|------------|---------------------|
| `OLLAMA_BASE_URL` | В Compose: `http://ollama:11434` |
| `MODEL_NAME` / `FALLBACK_MODEL` | Основная и запасная модель Ollama |
| `CONTEXT_SIZE` / `OLLAMA_NUM_PREDICT` | Параметры `num_ctx` / `num_predict` в запросе к Ollama |
| `RETRIEVAL_TOP_K` | Число чанков в промпт |
| `OLLAMA_HTTP_TIMEOUT_S` | Таймаут HTTP от `api` к Ollama (сек.) |

Полная таблица и обоснование дефолтов — в **INFO.md** и **`.env.example`**.

---

## Структура репозитория

| Путь | Содержание |
|------|------------|
| `docker-compose*.yml` | Стек Ollama + pull + API; GPU и hackathon override |
| `api/` | FastAPI-приложение, Dockerfile, `knowledge/`, статика UI |
| `scripts/` | Bootstrap моделей, диагностика Compose, сборка vendor JS |
| `tests/` | `run_eval.py`, `test_cases.json`, зависимости eval |
| `docs/jury/` | Чеклисты, спецификация интерфейса, операционные заметки |
| `artifacts/` | Примеры отчётов eval (при наличии в репозитории) |

---

## Документация

- [**INFO.md**](INFO.md) — поток запроса, API, ограничения.
- [**docs/jury/HACKATHON_CHECKLIST.md**](docs/jury/HACKATHON_CHECKLIST.md) — команды smoke / strict / GPU.
- [**docs/jury/INTERFACE_RUN.md**](docs/jury/INTERFACE_RUN.md) — запуск интерфейса для демо.

---

## Репозитории

**GitLab (сдача хакатона):** [git.truetecharena.ru/…/mts-localscript-lua-service](https://git.truetecharena.ru/mariakasimceva/mts-localscript-lua-service/-/tree/main)

**GitHub (зеркало):** [github.com/mariakasimceva0305-ux/mts-localscript-lua-service](https://github.com/mariakasimceva0305-ux/mts-localscript-lua-service) — description и topics заданы в настройках репозитория на GitHub.

