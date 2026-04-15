# LocalScript Handoff Package (Final Submission)

## Что входит в финальное решение

`LocalScript` — локальный генератор Lua для MWS Octapi (Ollama + FastAPI + retrieval + validator + reflexion), плюс freeze-ready интерфейс и пакет документов для жюри.

Проект готов к передаче как воспроизводимый набор:
- запуск через Docker Compose;
- стабильный strict-профиль для проверки;
- финальные артефакты прогонов с метриками.

## Ключевые папки и файлы

- `api/` — сервер, оркестратор, retrieval, validator, статика UI.
- `scripts/` — утилиты сборки и bootstrap.
- `tests/` — eval-скрипты и тест-кейсы.
- `docs/` — техническая и jury-документация.
- `artifacts/eval_live/` — отчёты прогонов.
- `docker-compose.yml` — базовый/freeze профиль.
- `docker-compose.hackathon.yml` — strict профиль (`num_predict=256`).
- `docker-compose.gpu.yml` — опционально, если есть рабочий NVIDIA runtime.
- `README.md`, `INFO.md`, `.env.example`.
- Операционный runbook: [MEMORY_AND_RUNTIME_CHECKS.md](MEMORY_AND_RUNTIME_CHECKS.md) (диск, VRAM, volumes, первый/повторный запуск).
- Скрипты диагностики: `scripts/compose_diagnostics.ps1`, `scripts/compose_diagnostics.sh`, `scripts/check_ollama_models.ps1`, `scripts/check_ollama_models.sh`, `scripts/compose_start_helper.ps1`, `scripts/compose_start_helper.sh`.

## Финальные артефакты (основные)

Использовать как baseline для сдачи:

1. `artifacts/eval_live/heavy_four_strict_after.json`
   - strict heavy_four: **4/4 success**

2. `artifacts/eval_live/report_hackathon_strict_after.json`
   - `total_cases=18`
   - `by_status: success=17, needs_clarification=1`
   - `transport_failed_case_ids=[]`
   - `success_rate=1.0`
   - `syntax_ok_rate=1.0`
   - `fallback_used_count=0`
   - clarification остался только в ожидаемом `ambiguous_short`.

## Исторические/вторичные артефакты

Оставлены для трассировки и сравнения, но не как submission-baseline:

- `artifacts/eval_live/heavy_four_after.json`
- `artifacts/eval_live/report_freeze_2026-04-13.json`
- другие старые `*_before`, `*_gpu`, `report.json`, `runs.jsonl`.

Рекомендация: не удалять автоматически; при передаче просто явно маркировать как historical.

## Команды запуска

Из корня проекта. Имя Docker-проекта **`localscript`** (см. `docker-compose.yml`, `.env.example`) — не меняйте без понимания последствий для volumes.

**Первый запуск / после смены `api/Dockerfile`:** `docker compose up --build`  
**Повторный** (модели уже в volume): `docker compose up -d`  
**Только API:** `docker compose up -d --build api`  
**Опасно:** `docker compose down -v` — сотрёт модели в volume, следующий старт снова скачает их.

```bash
cp .env.example .env
docker compose up --build
```

Strict-профиль:

```bash
docker compose -f docker-compose.yml -f docker-compose.hackathon.yml up --build
```

Быстрые проверки:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS http://127.0.0.1:8000/ready
```

Strict eval:

```bash
python -u tests/run_heavy_four.py --base-url http://127.0.0.1:8000 --timeout 720 --output artifacts/eval_live/heavy_four_strict_after.json
python -u tests/run_eval.py --base-url http://127.0.0.1:8000 --timeout 720 --output artifacts/eval_live/report_hackathon_strict_after.json --label strict_after_tuning
```

## Что уже закрыто

- Локальный инференс без внешних LLM API.
- Strict-профиль стабилен по итоговым метрикам.
- Clarification контролируемый: только ожидаемый неоднозначный кейс.
- Transport failures в финальном strict-прогоне отсутствуют.
- Интерфейс freeze-ready, без расширения scope.

## Что зависит от среды (не баг решения)

- Подтверждение VRAM/CPU-offload требует запуска на целевой машине с GPU и `nvidia-smi`.
- Нагрузка/латентность Ollama зависит от железа и фона.
- Сетевые ограничения (docker pull / TLS / proxy) зависят от окружения.

## Что показывать на защите в первую очередь

1. Коротко архитектуру (локально, без внешних AI API).
2. Финальные strict-артефакты и метрики из двух файлов baseline.
3. Демо пути `generate -> validation` и expected clarification на `ambiguous_short`.
4. Честно озвучить средовые ограничения GPU/VRAM как внешние к коду.

