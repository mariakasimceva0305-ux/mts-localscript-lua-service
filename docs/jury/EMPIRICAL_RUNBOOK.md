# Мини-прогоны: RETRIEVAL_TOP_K и OLLAMA_HTTP_TIMEOUT_S

Цель — сравнить конфигурации **на одном и том же подмножестве кейсов**, без подгонки под id.

Скрипт: **`tests/run_representative_subset.py`** (8 кейсов: heavy four + три обычных + один clarification).

**Важно:** `RETRIEVAL_TOP_K` и `OLLAMA_HTTP_TIMEOUT_S` читаются **контейнером `api`**. Между сериями пересоздайте `api` с нужными переменными.

---

## 1. Базовая команда (один прогон)

Из корня репозитория, при уже поднятом стеке:

```bash
pip install -r tests/requirements.txt
python -u tests/run_representative_subset.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --label describe_run \
  --output artifacts/sweep/subset_$(date +%Y%m%d_%H%M).json
```

В **`summary`** JSON смотрите: `transport_failed`, `success_count`, `syntax_ok_count`, `avg_latency_s`, `avg_gen1_prompt_chars`, `expect_clarification_hits`.

---

## 2. Сравнение `RETRIEVAL_TOP_K` ∈ {3, 4, 5, 6}

Используйте **один** профиль (freeze или strict) на всю серию, чтобы отличалось только k.

Пример (bash, strict):

```bash
export COMPOSE_FILES="-f docker-compose.yml -f docker-compose.hackathon.yml"
for k in 3 4 5 6; do
  RETRIEVAL_TOP_K=$k docker compose $COMPOSE_FILES up -d --build --force-recreate api
  sleep 15
  docker compose $COMPOSE_FILES ps
  python -u tests/run_representative_subset.py \
    --base-url http://127.0.0.1:8000 \
    --timeout 720 \
    --label "strict_topk_${k}" \
    --output "artifacts/sweep/strict_topk_${k}.json"
done
```

Проверка env:

```bash
docker exec lua-gen-api printenv RETRIEVAL_TOP_K CONTEXT_SIZE OLLAMA_NUM_PREDICT
```

### Таблица результатов (заполнить локально)

| RETRIEVAL_TOP_K | transport_failed | success (7 gen) | syntax_ok (7 gen) | avg_latency_s | avg_gen1_prompt_chars | Примечание |
|-----------------|------------------|-----------------|-------------------|---------------|------------------------|------------|
| 3 | | | | | | |
| 4 | | | | | | |
| 5 | | | | | | |
| 6 | | | | | | |

**Критерий выбора (рекомендация жюри/команды):**

1. Минимум **`transport_failed`** (в т.ч. нет `ReadTimeout` на подмножестве).
2. Максимум **`success_count`** и **`syntax_ok_count`** среди gen-кейсов.
3. При равенстве — меньше **`avg_latency_s`** и/или **`avg_gen1_prompt_chars`** (короче промпт — меньше давление на `num_ctx` / обрезку ответа).

**Текущее решение репозитория (до заполнения таблицы):** freeze-дефолт **`RETRIEVAL_TOP_K=4`**. После локального прогона при необходимости обновите `docker-compose.yml`, `.env.example` и этот runbook одним согласованным значением.

---

## 3. Сравнение `OLLAMA_HTTP_TIMEOUT_S` ∈ {220, 240, 260}

Фиксируйте **`RETRIEVAL_TOP_K=4`** (или выбранное по п.2). Меняйте только таймаут.

Пример с временным override (создайте файл и подключите третьим `-f` или экспортируйте на хосте):

```bash
# Вариант A: в .env на время прогона задайте OLLAMA_HTTP_TIMEOUT_S, затем:
# docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up -d --build --force-recreate api
python -u tests/run_representative_subset.py ... --label timeout_220 ...
```

Повторите для 240 и 260.

### Таблица (заполнить локально)

| OLLAMA_HTTP_TIMEOUT_S | transport_failed | success | syntax_ok | avg_latency_s | max_latency_s | ReadTimeout в логах |
|----------------------|------------------|---------|-----------|---------------|---------------|---------------------|
| 220 | | | | | | |
| 240 | | | | | | |
| 260 | | | | | | |

**Итоговое значение в репозитории: `240` с** — баланс между обрывами при reflexion/длинной генерации (типично хуже при **220**, см. закоммиченные отчёты) и неразумным ожиданием при зависаниях (**260** не даёт гарантированного выигрыша качества, только удлиняет хвост).

---

## 4. Строгий профиль + тяжёлые прогоны

После выбора параметров зафиксируйте метрики:

```bash
python -u tests/run_heavy_four.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --output artifacts/eval_live/heavy_four_strict.json

python -u tests/run_eval.py \
  --base-url http://127.0.0.1:8000 \
  --timeout 720 \
  --output artifacts/eval_live/report_hackathon_strict.json \
  --label hackathon_strict
```

См. [HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md).
