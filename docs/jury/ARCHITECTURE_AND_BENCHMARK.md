# Architecture and Benchmark (LocalScript)

Цель этого блока — дать жюри и коллегам короткое, инженерно понятное объяснение: как устроена система, какие проблемы были до тюнинга, что реально улучшилось, и почему текущая конфигурация retrieval выбрана осознанно.

## 1) Архитектура: управляемый оркестраторный контур

LocalScript построен не как "хаотический multi-agent", а как управляемый pipeline с явными шагами:

1. **Orchestrator (`api/orchestrator.py`)**  
   Принимает запрос, определяет режим (generate/edit/clarification), собирает prompt, запускает модель, извлекает код, валидирует результат и формирует единый ответ API.
2. **Coder (LLM через Ollama)**  
   Генерирует Lua-код по инструкции и контексту. Основная модель: `qwen2.5-coder:7b`; fallback используется только при инфраструктурном сбое.
3. **Retrieval (`api/retriever.py`)**  
   Подмешивает релевантные фрагменты знаний (BM25 + keyword bonus) и уменьшает вероятность "пустой фантазии" модели.
4. **Validation (`api/validator.py`)**  
   Проверяет синтаксис Lua (`luac`) и доменные ограничения (`wf.vars`, `wf.initVariables`, запрет опасных вызовов).
5. **Clarification / second pass / fallback**  
   - `needs_clarification` включается только для реально недостаточных запросов по эвристикам оркестратора.  
   - Второй проход (reflexion) включается только при провале синтаксики после первого pass.  
   - Fallback-модель — только на транспортных/инфраструктурных ошибках, не как "магическое улучшение качества".

### Почему оркестратор на Python

- Явная и воспроизводимая логика маршрутизации.
- Контролируемая интеграция с retrieval и validator.
- Четкая трассировка и диагностика по этапам в одном сервисе.

## 2) Разбор ошибок по типам

Ниже категории, которые отслеживались в strict-профиле:

- **Лишние clarification**  
  Ранее возникали на доменно понятных коротких запросах (`init_variable`) и даже в edit-сценарии (`edit_mode_sample`).
- **Transport failures / timeout**  
  Основной ранний источник деградации: часть кейсов не доходила до содержательного ответа (`timed out` / `ReadTimeout`).
- **Синтаксические ошибки Lua**  
  В финальном strict-прогоне среди успешных генераций не наблюдаются (`syntax_ok_rate=1.0`).
- **Retrieval-проблемы (раздувание prompt/шум)**  
  Ранний heavy-run показывал более тяжелый retrieval-контур (`retrieval_chunks_count=6`) и большие prompt.
- **Высокая latency**  
  Ранее латентность strict-прогона была существенно выше и сопровождалась timeout'ами.
- **Ошибки режимов edit/generate/validate**  
  Основная проблема была в маршрутизации edit/generate (лишний clarification), не в `validate`.

В финальном strict (`report_hackathon_strict_after.json`) отсутствуют transport-fail, а clarification остался ровно в ожидаемом ambiguous-сценарии.

## 3) Что улучшилось после последнего тюнинга

Сравнение "было -> стало" по ключевым артефактам:

### Full strict eval

- **Было** (`artifacts/eval_live/report_hackathon_strict.json`):  
  `success=9`, `needs_clarification=3`, `transport_failed_case_ids=6`.
- **Стало** (`artifacts/eval_live/report_hackathon_strict_after.json`):  
  `success=17`, `needs_clarification=1`, `transport_failed_case_ids=[]`, `success_rate=1.0`, `syntax_ok_rate=1.0`, `fallback_used_count=0`.
- **Причина улучшения**:  
  менее агрессивная clarification-эвристика для доменных/edit-подсказок + облегченный prompt/retrieval-контур.

### Heavy four

- **Было** (`artifacts/eval_live/heavy_four_before.json`):  
  только 1/4 success, частые `ReadTimeout`, `retrieval_chunks_count=6`, `num_predict=320`.
- **Стало** (`artifacts/eval_live/heavy_four_strict_after.json`):  
  4/4 success, без transport failures, `retrieval_chunks_count=4` и заметно меньший `gen1_prompt_chars`.
- **Причина улучшения**:  
  более компактная генерация и умеренный retrieval budget в strict-профиле.

## 4) Retrieval benchmark (компактный)

### Что удалось подтвердить по артефактам

Подтвержденное сравнение из уже сохраненных прогонов:

| Конфигурация | Источник | Результат | Комментарий |
|---|---|---|---|
| `top_k≈6` (ранний heavy) | `heavy_four_before.json` | 1/4 success, timeout'ы | Перегруженный retrieval/prompt путь |
| `top_k=4` (после тюнинга) | `heavy_four_after.json`, `heavy_four_strict_after.json` | 4/4 success, без transport-fail | Стабильный баланс качества/латентности |

### Про `top_k=3` vs `top_k=4`

В этом раунде отдельно запущен representative subset с `top_k=3` и сохранен в `artifacts/sweep/strict_topk_3.json`.  
Результат: только 1 корректно завершенный кейс из 8, далее серия `RemoteProtocolError` / `ReadError` (разрыв соединения), поэтому прогон нельзя использовать как чистое quality-сравнение retrieval.

Итог по инженерной интерпретации:

- baseline `top_k=4` подтвержден стабильными боевыми артефактами (`heavy_four_after`, `heavy_four_strict_after`, `report_hackathon_strict_after`);
- `top_k=3` в текущей среде дал инфраструктурно нестабильный прогон и не показал основания для смены baseline;
- для полноценного парного сравнения `top_k=3/4` используется reproducible процедура из `docs/jury/EMPIRICAL_RUNBOOK.md`.

## 5) Почему текущий вариант инженерно сильный

- Не "полагается на удачу модели": есть retrieval + validation + управляемая оркестрация.
- Не перегружен искусственной сложностью: один воспроизводимый контур вместо хрупкого набора автономных агентов.
- Улучшения подтверждены метриками strict-прогонов, а не только качественными примерами.

## 6) Что можно делать следующим этапом после freeze

Roadmap без признания текущего решения слабым:

- более широкий retrieval-benchmark (`top_k=3/4/5`) на расширенном representative subset;
- дальнейшая фильтрация retrieval-шума по источникам;
- аккуратное разделение ролей моделей (если появится отдельная инфраструктурная цель);
- опциональная серверная память/профили как отдельный продуктовый этап (вне текущего freeze scope).

## 7) Итог для защиты

На текущем этапе LocalScript можно защищать как зрелое локальное инженерное решение:

- оркестраторный контур объясним и воспроизводим;
- основные риски (лишний clarification, timeout-heavy strict) после тюнинга закрыты;
- финальные strict-артефакты демонстрируют стабильность без деградации синтаксики.

