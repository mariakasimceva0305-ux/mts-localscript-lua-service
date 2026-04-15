# Release Contents (Final Archive Checklist)

## Включить в финальный архив

- `api/`
- `docs/`
- `scripts/`
- `tests/`
- `artifacts/eval_live/`
  - обязательно: `heavy_four_strict_after.json`, `report_hackathon_strict_after.json`
- `docker-compose.yml`
- `docker-compose.hackathon.yml`
- `docker-compose.gpu.yml` (опционально, но рекомендуется оставить)
- `README.md`
- `INFO.md`
- `.env.example`
- `docs/jury/MEMORY_AND_RUNTIME_CHECKS.md` (операционный runbook: диск, VRAM, volumes)
- `package.json` и `package-lock.json` (для vendor-сборки интерфейса)

## Не включать / не делать обязательным

- `.env`
- `.idea/`
- `__pycache__/`
- локальные временные/служебные файлы ОС
- локальные логи терминала и промежуточные служебные дампы

## Отчёты: как не запутать получателя

- **Final baseline:**  
  - `artifacts/eval_live/heavy_four_strict_after.json`  
  - `artifacts/eval_live/report_hackathon_strict_after.json`

- **Historical (для сравнения):** остальные отчёты в `artifacts/eval_live/`.

Если в архив включаются все отчёты, в сопроводительном письме/README явно указать, что baseline — только два файла выше.

