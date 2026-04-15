"""Системные промпты и few-shot примеры для генерации Lua."""

from __future__ import annotations

import os
from typing import Any


def safe_prompt_format(template: str, **kwargs: Any) -> str:
    """Подставляет {name} в шаблон; значения могут содержать «{» и «}» (в отличие от str.format)."""
    out = template
    for key, val in sorted(kwargs.items(), key=lambda kv: len(kv[0]), reverse=True):
        out = out.replace("{" + key + "}", str(val))
    return out


def plan_instruction_line() -> str:
    """Короче план — меньше токенов на ответ; включается env GENERATION_COMPACT_PLAN."""
    if os.environ.get("GENERATION_COMPACT_PLAN", "").lower() in ("1", "true", "yes"):
        return "Перед ```lua — одна короткая строка-план (до 6 слов) или сразу код."
    return "Перед тем как писать код, кратко опиши план действий (2-3 предложения)."


SYSTEM_GENERATION_TEMPLATE = """Ты — ассистент для написания Lua-скриптов в среде MWS Octapi Low-Code.
Используй только релевантные фрагменты документации и правила ниже.
{plan_instruction}
Код должен быть возвращён в блоке ```lua ... ```.
После блока кода добавь одно короткое инженерное пояснение (до 12 слов).
Убедись, что код синтаксически корректен для Lua в среде Octapi; локальная проверка в контейнере — через Lua 5.5 (luac).

### Документация (извлечённые фрагменты):
{retrieved_snippets}

### Few-shot примеры (стиль ответа):
{few_shot}

### Правила:
- Все переменные из LowCode находятся в `wf.vars`.
- Начальные переменные из `variables` – в `wf.initVariables`.
- Для создания массива используй `_utils.array.new()`.
- Запрещено использовать `os.execute`, `io.*`, `debug.*`.
- Возвращаемое значение должно быть последним выражением в скрипте (или используй `return`).
"""

CLARIFICATION_PROMPT_TEMPLATE = """Пользователь хочет: {prompt}
Тебе не хватает деталей. Задай один короткий уточняющий вопрос на русском языке."""

REPAIR_PROMPT_TEMPLATE = """Твой предыдущий код содержит ошибку:
{error_message}

Код:
{original_code}

Исправь ошибку и верни исправленный код в блоке ```lua. Сохрани смысл задачи."""

# Второй проход (Reflexion): та же модель, полный контекст валидации + задача + код.
REVIEW_REFLEXION_PROMPT_TEMPLATE = """Второй проход (самопроверка): улучши и исправь финальный Lua для Octapi Low-Code.

### Исходная задача пользователя:
{user_task}

### Код после первого прохода:
```lua
{current_code}
```

### Результат валидации (luac 5.5 + доменные правила в контейнере API):
- syntax_ok: {syntax_ok}
- hard_errors (нужно устранить, иначе скрипт неприемлем):
{hard_errors_block}
- warnings (желательно учесть, если не противоречит задаче):
{warnings_block}
- hints (учти по возможности):
{hints_block}

Сделай:
1. Устрани все причины, по которым валидация не проходит (syntax_ok=false или hard_errors).
2. По возможности снизь количество warnings, не меняя смысл задачи.
3. Верни только итоговый код в одном блоке ```lua ... ``` без текста после закрывающих ```.
"""

EDIT_MODE_PREFIX = """Режим правки существующего скрипта. Учти текущий код и требование пользователя.
Текущий код:
```lua
{previous_code}
```
Задача (изменение / дополнение):
"""

FEW_SHOT_BLOCK = """
Пример 1 — последний элемент массива:
Запрос: верни последний элемент массива wf.vars.emails
Ответ:
```lua
return wf.vars.emails[#wf.vars.emails]
```

Пример 2 — имя пользователя:
Запрос: верни значение userName из wf.vars
Ответ:
```lua
return wf.vars.userName
```
"""
