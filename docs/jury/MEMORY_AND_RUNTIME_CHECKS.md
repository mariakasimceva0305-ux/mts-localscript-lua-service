# LocalScript: память (диск, VRAM) и проверки рантайма

Краткий технический справочник для команды: что можно измерить без GPU, что требует NVIDIA, как отличить «модели на диске» от «память во время генерации».

---

## 1. Две разные «памяти»

| Что | Где | Как смотреть |
|-----|-----|----------------|
| **Хранение моделей Ollama** | Docker volume (в репозитории логически `ollama_data` → на хосте управляется Docker) | `docker volume ls`, размер данных на диске, `ollama list` внутри контейнера |
| **VRAM GPU** | Видеопамять во время инференса | Только на машине с NVIDIA + драйвером: `nvidia-smi` |
| **RAM хоста / контейнеров** | Оперативная память процессов | Docker stats, диспетчер задач; на CPU инференс Ollama использует RAM |

Путаница «модели скачиваются заново» чаще всего из‑за **нового имени Compose-проекта** → новые volumes → пустой каталог моделей. В репозитории проект зафиксирован как **`localscript`** (`name:` в `docker-compose.yml` + рекомендация `COMPOSE_PROJECT_NAME=localscript` в `.env.example`).

Если вы уже работали со стеком **до** фиксации имени и на хосте остались volumes вроде **`староеимя_ollama_data`**, новый стек использует **`localscript_ollama_data`** — это **другой** volume, первый `ollama-pull` снова скачает модели (однократно). Перенос данных между volumes вручную возможен, но выходит за рамки baseline; проще один раз дождаться pull в новый volume.

---

## 2. Без NVIDIA: что можно честно подтвердить

- **Образы и контейнеры** подняты, **healthcheck** `ollama` / `lua-gen-api` — **healthy**.
- **`GET /ready`** — Ollama доступен с точки зрения API, в каталоге есть нужные теги моделей.
- **Модели в volume**: `docker exec ollama ollama list` — видны `qwen2.5-coder:7b` и `deepseek-coder:6.7b` (или смысловые эквиваленты из `MODEL_NAME` / `FALLBACK_MODEL`).
- **Диск**: модели Ollama занимают **много гигабайт**; первый `pull` долгий, повторный — быстрый (идемпотентный), если volume тот же.

**Нельзя** без GPU доказать пик **VRAM**, отсутствие CPU offload вцифрах, или укладку в «≤ 8 ГБ VRAM» — только гипотеза до замера на целевом железе.

---

## 3. С NVIDIA: замер VRAM и пиковая нагрузка

Во время **`POST /generate`**, heavy four или длинной генерации во **втором** терминале:

```bash
watch -n 1 nvidia-smi
# или
nvidia-smi dmon -s u
# или раз в секунду:
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv -l 1
```

Фиксируйте **максимум** `memory.used` на окне нагрузки — это оценка пика для данного железа и версии Ollama.

---

## 4. Диск: volumes и «не терять» модели

Имена volumes формируются как **`<compose_project>_<volume_name>`**, например `localscript_ollama_data`.

Проверка:

```bash
docker volume ls | grep -E 'ollama|localscript'
docker compose ls
```

Скрипты в репозитории: `scripts/compose_diagnostics.sh` / `scripts/compose_diagnostics.ps1`.

**Опасно:** `docker compose down -v` — удаляет **именованные volumes** проекта (в том числе с моделями). Следующий `up` снова запустит `ollama-pull` и скачает модели.

**Безопаснее:** `docker compose down` (без `-v`) — контейнеры останавливаются, данные в volumes остаются.

---

## 5. Почему первый запуск 20–40+ минут, а повторный быстрее

| Этап | Первый запуск | Повторный (тот же volume) |
|------|----------------|----------------------------|
| `docker compose pull` / скачивание образов | Да, если образов нет | Обычно коротко |
| Сборка `api` (`--build`) | Полная сборка слоёв | Часто кэш, быстрее |
| **`ollama-pull`** | Полный `pull` двух моделей (ГБ трафика и диска) | `ollama pull` идемпотентен: уже есть локально — почти без скачивания |
| Старт Ollama | Прогрев | Быстрее |

Долгий старт **не** означает обязательно «всё с нуля»: смотрите логи `ollama-pull` (`[ollama-pull] OK` / `READY`).

---

## 6. Быстрые команды статуса

Из корня репозитория:

```bash
docker compose ps
docker compose logs --tail 80 ollama-pull
docker exec ollama ollama list
curl -sS http://127.0.0.1:8000/ready
```

Windows (PowerShell): см. `scripts/compose_diagnostics.ps1`.

---

## 7. Связанные документы

- [HACKATHON_CHECKLIST.md](HACKATHON_CHECKLIST.md) — команды freeze / strict / smoke.
- [HANDOFF_PACKAGE.md](HANDOFF_PACKAGE.md) — передача проекта.
- [OPERATIONS_AND_SCALING.md](OPERATIONS_AND_SCALING.md) — эксплуатация.
- [README.md](../../README.md) — полный запуск и раздел про операционный цикл.
