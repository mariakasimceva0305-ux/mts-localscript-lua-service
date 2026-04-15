# LocalScript: чеклист команд (freeze / strict / eval / GPU)

Копируйте блоки из корня репозитория. **Проверено:** соответствует `docker-compose.yml`, `docker-compose.hackathon.yml`, `tests/run_eval.py`.

**Имя Compose-проекта:** в базовом `docker-compose.yml` задано `name: localscript`; в `.env.example` — `COMPOSE_PROJECT_NAME=localscript`. Одинаковые volumes (`localscript_ollama_data` и др.) при любом пути к коду — иначе при другом имени проекта модели окажутся в новом volume и **`ollama-pull` снова скачает гигабайты**. Диагностика: `scripts/compose_diagnostics.sh` / `.ps1`. Память диск/VRAM: [MEMORY_AND_RUNTIME_CHECKS.md](MEMORY_AND_RUNTIME_CHECKS.md).

---

## 1. Freeze-конфиг (разработка, `num_predict=288`)

```bash
cp .env.example .env   # рекомендуется (COMPOSE_PROJECT_NAME и дефолты)
docker compose up --build
docker compose ps      # дождаться healthy: ollama, lua-gen-api
```

Повторный запуск без пересборки образов: `docker compose up -d`. Только API после правок в `api/`: `docker compose up -d --build api`. **Не использовать** `docker compose down -v` без необходимости — **`-v` удаляет volumes с моделями**.

Windows (нестабильный pull):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\compose_up_retry.ps1
```

---

## 2. Strict hackathon (`num_predict=256`, `num_ctx=4096`, `OLLAMA_NUM_PARALLEL=1`)

Параметры заданы в **`docker-compose.hackathon.yml`** (override). Базовый **`docker-compose.yml`** не меняется.

```bash
docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build
```

С GPU (NVIDIA):

```bash
docker compose -f docker-compose.yml -f docker-compose.hackathon.yml -f docker-compose.gpu.yml up --build
```

Справка по env: **`.env.hackathon.example`**.

Проверка **фактических** значений в контейнерах после старта strict:

```bash
docker exec lua-gen-api printenv CONTEXT_SIZE OLLAMA_NUM_PREDICT OLLAMA_HTTP_TIMEOUT_S RETRIEVAL_TOP_K
docker exec ollama printenv OLLAMA_NUM_PARALLEL
```

Ожидание: `4096`, `256`, `240`, (типично) `4`, и `1`.

---

## 3. Smoke: `/health`, `/ready`, `/models`, `/generate`

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS -w "\nHTTP %{http_code}\n" http://127.0.0.1:8000/ready
curl -sS http://127.0.0.1:8000/models
curl -sS -X POST http://127.0.0.1:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"верни значение wf.vars.userName","context":null}'
```

Ожидание: `/health` → `{"ok":true}`; `/ready` → `200` и готовность к генерации; `/generate` → `success`, `validation.syntax_ok: true` для примера выше.

Версия компилятора в контейнере `api` (ожидается **Lua 5.5.x**):

```bash
docker exec lua-gen-api sh -c "command -v luac && luac -v"
```

---

## 4. Heavy four

```bash
pip install -r tests/requirements.txt
python -u tests/run_heavy_four.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --output artifacts/eval_live/heavy_four_strict.json
```

(Имя файла выхода замените при необходимости.)

---

## 4b. Репрезентативное подмножество (8 кейсов, для сравнения top_k / timeout)

См. **[EMPIRICAL_RUNBOOK.md](EMPIRICAL_RUNBOOK.md)**. Кратко:

```bash
python -u tests/run_representative_subset.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --label my_label \
  --output artifacts/sweep/subset.json
```

---

## 5. Полный eval

```bash
python -u tests/run_eval.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --output artifacts/eval_live/report_hackathon_strict.json \
  --label hackathon_strict
```

---

## 6. GPU и VRAM (`nvidia-smi`)

Во время нагрузки (второй терминал):

```bash
watch -n 1 nvidia-smi
# или
nvidia-smi dmon -s u
```

Снять пик использования памяти:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv -l 1
```

---

## 7. CPU offload (ориентиры, без гарантии по версии Ollama)

- Запуск только с **`docker-compose.gpu.yml`**, без принудительного CPU-режима для Ollama (в репозитории таких переменных нет).
- В **`nvidia-smi`**: ненулевая утилизация GPU во время генерации; рост **`memory.used`** на GPU.
- Логи: `docker compose logs ollama` — при сомнениях сверяйте с документацией **вашей** версии образа `ollama/ollama` (формулировки про offload могут отличаться).

**Итог:** отсутствие offload однозначно доказывается только на вашей машине с корректным драйвером и NVIDIA Container Toolkit.

---

## 8. Проверка фактических env (повтор)

Полный набор для strict — в **§2** (`printenv` + `RETRIEVAL_TOP_K`). Здесь — короткий вариант:

```bash
docker exec lua-gen-api printenv CONTEXT_SIZE OLLAMA_NUM_PREDICT OLLAMA_HTTP_TIMEOUT_S
docker exec ollama printenv OLLAMA_NUM_PARALLEL
```
