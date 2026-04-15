"""Orchestration: clarify router, retrieval, generation, validation, reflexion."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from prompts import (
    CLARIFICATION_PROMPT_TEMPLATE,
    EDIT_MODE_PREFIX,
    FEW_SHOT_BLOCK,
    REVIEW_REFLEXION_PROMPT_TEMPLATE,
    SYSTEM_GENERATION_TEMPLATE,
    plan_instruction_line,
    safe_prompt_format,
)
from retriever import retrieve_for_generation
from validator import ValidationResult, validate_lua_code, validation_to_api_dict

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")
MODEL_NAME = os.environ.get("MODEL_NAME", "qwen2.5-coder:7b")
FALLBACK_MODEL = os.environ.get("FALLBACK_MODEL", "deepseek-coder:6.7b")
CONTEXT_SIZE = int(os.environ.get("CONTEXT_SIZE", "4096"))
NUM_PREDICT = int(os.environ.get("OLLAMA_NUM_PREDICT", "320"))
_OLLAMA_READ_TIMEOUT = float(os.environ.get("OLLAMA_HTTP_TIMEOUT_S", "120"))
GENERATE_TIMEOUT = httpx.Timeout(_OLLAMA_READ_TIMEOUT, connect=30.0)

CLARIFY_YES_NO_TEMPLATE = """Определи, достаточно ли информации для написания Lua-кода по этому запросу.
Ответь только "YES" или "NO".
Запрос: {prompt}
"""

_EDIT_MARKERS = (
    "исправ",
    "правк",
    "доработ",
    "измени",
    "замени",
    "перепиши",
    "update",
    "modify",
    "fix",
    "edit",
)

_DOMAIN_MARKERS = (
    "wf.vars",
    "wf.initvariables",
    "_utils.array",
    "octapi",
    "lua",
    "return",
    "массив",
    "array",
    "script",
    "скрипт",
    "variable",
    "перемен",
    "init",
)

_DOMAIN_TOKEN_MARKERS = (
    "wf",
    "vars",
    "initvariables",
    "initvariable",
    "octapi",
    "lua",
    "return",
    "массив",
    "array",
    "script",
    "скрипт",
    "variable",
    "перемен",
    "инициал",
    "init",
)

EDIT_REQUEST_TEMPLATE = """У тебя есть следующий Lua-код:
```lua
{original_code}
```
Пользователь просит: {instruction}
Внеси изменения в код, сохранив остальную логику, и верни новый код в блоке ```lua.
"""


class OllamaApiError(Exception):
    """HTTP 200, but Ollama JSON contains `error`."""


@dataclass(frozen=True)
class OllamaGenResult:
    text: str
    used_model: str
    fallback_used: bool
    fallback_reason: str | None


def _join_message(errors: list[str]) -> str:
    return " | ".join(errors) if errors else ""


def _model_response_fields(gen: OllamaGenResult) -> dict[str, Any]:
    return {
        "used_model": gen.used_model,
        "fallback_used": gen.fallback_used,
        "fallback_reason": gen.fallback_reason,
    }


def _ollama_validation_dict(errs: list[str]) -> dict[str, Any]:
    e = list(errs)
    return {"syntax_ok": False, "hard_errors": e, "warnings": [], "hints": [], "errors": e}


def _extract_previous_code(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    for key in ("previous_code", "code", "lua", "script"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# Ограничение блока «чат из UI» в промпте (клиент шлёт recent_messages и summary).
_UI_CHAT_CONTEXT_MAX_CHARS = 1400


def _format_ui_chat_context(context: dict[str, Any] | None) -> str | None:
    """Включает в промпт поля context из фронта (история чата), если они есть."""
    if not isinstance(context, dict):
        return None
    chunks: list[str] = []

    pend = context.get("pending_clarification")
    if isinstance(pend, dict):
        op = (pend.get("original_prompt") or "").strip()
        q = (pend.get("question") or "").strip()
        if op or q:
            sub = []
            if op:
                sub.append(f"исходный запрос: {op}")
            if q:
                sub.append(f"вопрос на уточнение: {q}")
            chunks.append("Уточнение (состояние UI):\n" + "\n".join(sub))

    summary = context.get("chat_summary")
    if isinstance(summary, str) and summary.strip():
        chunks.append(f"Краткий контекст чата: {summary.strip()[:650]}")

    recent = context.get("recent_messages")
    if isinstance(recent, list) and recent:
        lines: list[str] = []
        for m in recent[-6:]:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role", "")).strip()
            text = str(m.get("text", "")).strip()[:260]
            if role and text:
                lines.append(f"  - {role}: {text}")
        if lines:
            chunks.append("Недавние реплики:\n" + "\n".join(lines))

    lut = context.get("last_user_task")
    if isinstance(lut, str) and lut.strip():
        chunks.append(f"Последняя задача пользователя: {lut.strip()[:420]}")

    lar = context.get("last_assistant_response")
    if isinstance(lar, str) and lar.strip():
        chunks.append(f"Последний ответ ассистента: {lar.strip()[:420]}")

    if not chunks:
        return None
    block = "\n\n".join(chunks)
    if len(block) > _UI_CHAT_CONTEXT_MAX_CHARS:
        block = block[: _UI_CHAT_CONTEXT_MAX_CHARS - 1] + "…"
    return (
        "### Контекст диалога (из интерфейса; на сервере история не хранится)\n"
        f"{block}\n\nУчти этот контекст при ответе на текущую задачу ниже."
    )


def _looks_like_edit_request(prompt: str, previous_code: str | None) -> bool:
    if previous_code:
        return True
    p = (prompt or "").lower()
    if any(marker in p for marker in _EDIT_MARKERS):
        return True
    # Доп. сигнал edit-mode: короткие инженерные формулировки с "код/скрипт/lua".
    has_edit_verb = bool(re.search(r"\b(fix|edit|modify|update)\b", p)) or any(
        s in p for s in ("исправ", "правк", "доработ", "перепиши", "измени")
    )
    has_code_noun = any(s in p for s in ("код", "скрипт", "lua"))
    return has_edit_verb and has_code_noun


def _is_domain_grounded(prompt: str) -> bool:
    p = (prompt or "").strip().lower()
    if not p:
        return False
    if any(marker in p for marker in _DOMAIN_MARKERS):
        return True
    terms = set(re.findall(r"[\w\u0400-\u04FF]{2,}", p))
    if not terms:
        return False
    return any(tok in terms for tok in _DOMAIN_TOKEN_MARKERS)


def _should_force_clarification_heuristic(prompt: str, previous_code: str | None) -> bool:
    # Режим правки подавляет уточнение почти полностью: код + инструкция обычно достаточно конкретны.
    if _looks_like_edit_request(prompt, previous_code):
        return False

    p = (prompt or "").strip().lower()
    if not p:
        return True

    terms = re.findall(r"[\w\u0400-\u04FF]{2,}", p)
    short = len(terms) <= 3
    has_domain = _is_domain_grounded(p)
    # Короткий и без доменной опоры: лучше уточнить (ambiguous_short должен оставаться тут).
    return short and not has_domain


def _validation_response(v: ValidationResult, extra_hard: list[str] | None = None) -> dict[str, Any]:
    base = validation_to_api_dict(v)
    if not extra_hard:
        return base
    he = list(base["hard_errors"]) + list(extra_hard)
    return {**base, "hard_errors": he, "errors": he + list(base["warnings"]) + list(base["hints"])}


def _should_retry_with_fallback(exc: BaseException) -> bool:
    if isinstance(exc, (OllamaApiError, httpx.RequestError, json.JSONDecodeError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500 or exc.response.status_code == 404
    return False


def _fallback_reason_from_exc(exc: BaseException) -> str:
    if isinstance(exc, OllamaApiError):
        return f"ollama_api_error:{str(exc)[:200]}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.RequestError):
        return f"request_error:{type(exc).__name__}"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"http_{exc.response.status_code}"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json_response"
    return f"unexpected:{type(exc).__name__}"


def _ollama_base_url_candidates() -> list[str]:
    primary = OLLAMA_BASE_URL.rstrip("/")
    out: list[str] = [primary]
    if "://ollama:11434" in primary:
        out.extend(
            [
                primary.replace("://ollama:11434", "://127.0.0.1:11434"),
                primary.replace("://ollama:11434", "://localhost:11434"),
                primary.replace("://ollama:11434", "://host.docker.internal:11434"),
            ]
        )
    # Удаляем дубликаты с сохранением порядка.
    return list(dict.fromkeys(out))


async def _ollama_generate(client: httpx.AsyncClient, model: str, prompt: str) -> str:
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": CONTEXT_SIZE, "num_predict": NUM_PREDICT},
    }
    last_exc: Exception | None = None
    for base_url in _ollama_base_url_candidates():
        try:
            r = await client.post(f"{base_url}/api/generate", json=payload, timeout=GENERATE_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("error"):
                raise OllamaApiError(str(data["error"]))
            return str(data.get("response", ""))
        except Exception as e:  # noqa: PERF203
            last_exc = e
            continue
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Ollama base URL candidates are empty")


async def generate_with_infra_fallback(
    client: httpx.AsyncClient,
    prompt: str,
    *,
    call_label: str = "generate",
) -> OllamaGenResult:
    try:
        out = await _ollama_generate(client, MODEL_NAME, prompt)
        logger.info("[%s] model=%s fallback=False", call_label, MODEL_NAME)
        return OllamaGenResult(out, MODEL_NAME, False, None)
    except Exception as e:
        if not _should_retry_with_fallback(e):
            raise
        reason = _fallback_reason_from_exc(e)
        out = await _ollama_generate(client, FALLBACK_MODEL, prompt)
        logger.warning("[%s] model=%s fallback=True reason=%s", call_label, FALLBACK_MODEL, reason)
        return OllamaGenResult(out, FALLBACK_MODEL, True, reason)


def extract_lua_block(text: str) -> str | None:
    if not text or not text.strip():
        return None
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    patterns = [r"```lua\s*\n(.*?)```", r"```lua\s+(.*?)```", r"```\s*\n(.*?)```", r"```lua\s*(.*?)```"]
    for pat in patterns:
        m = re.search(pat, t, re.DOTALL | re.IGNORECASE)
        if m:
            code = m.group(1).strip()
            if code:
                return code
    open_match = re.search(r"```lua\s*(.*)", t, re.DOTALL | re.IGNORECASE)
    if open_match:
        tail = open_match.group(1).split("```", 1)[0].strip()
        return tail or None
    return None


def extract_explanation(text: str) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(r"```(?:lua)?\s*.*?```(.*)$", normalized, re.DOTALL | re.IGNORECASE)
    if not m:
        return ""
    explanation = re.sub(r"\s+", " ", m.group(1)).strip()
    return explanation[:500]


async def _needs_clarification_llm(client: httpx.AsyncClient, prompt: str) -> tuple[bool, OllamaGenResult]:
    check_prompt = safe_prompt_format(CLARIFY_YES_NO_TEMPLATE, prompt=prompt)
    result = await generate_with_infra_fallback(client, check_prompt, call_label="clarify_router")
    answer = (result.text or "").strip().upper()
    return answer.startswith("NO"), result


def _base_result(status: str, **kwargs: Any) -> dict[str, Any]:
    payload = {
        "status": status,
        "code": "",
        "clarifying_question": "",
        "message": "",
        "validation": {"syntax_ok": False, "hard_errors": [], "warnings": [], "hints": [], "errors": []},
        "iterations": 1,
        "first_pass_syntax_ok": None,
        "reflexion_applied": False,
        "retrieved_chunks": [],
        "explanation": "",
    }
    payload.update(kwargs)
    return payload


async def _run_generation_pipeline(
    client: httpx.AsyncClient,
    *,
    task_prompt: str,
    user_prompt: str,
    previous_code: str | None,
    include_diagnostics: bool,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rag = retrieve_for_generation(user_prompt, previous_code or "")
    snippets = rag.get("formatted", "")
    retrieved_chunks = rag.get("chunks", [])

    system_part = safe_prompt_format(
        SYSTEM_GENERATION_TEMPLATE,
        plan_instruction=plan_instruction_line(),
        retrieved_snippets=snippets,
        few_shot=FEW_SHOT_BLOCK,
    )
    user_parts: list[str] = []
    if previous_code:
        user_parts.append(safe_prompt_format(EDIT_MODE_PREFIX, previous_code=previous_code))
    ui_ctx = _format_ui_chat_context(context)
    if ui_ctx:
        user_parts.append(ui_ctx)
    user_parts.append(f"Задача пользователя:\n{task_prompt}")
    full_prompt = f"{system_part}\n\n" + "\n\n".join(user_parts)

    diag: dict[str, Any] | None = {} if include_diagnostics else None
    if diag is not None:
        diag["retrieval_chunks_count"] = len(retrieved_chunks)
        diag["gen1_prompt_chars"] = len(full_prompt)

    gen_main = await generate_with_infra_fallback(client, full_prompt, call_label="main")
    raw = gen_main.text
    code = extract_lua_block(raw)
    explanation = extract_explanation(raw)
    if not code:
        errs = ["Не найден блок ```lua в ответе модели."]
        return _base_result(
            "error",
            message=_join_message(errs),
            validation=_ollama_validation_dict(errs),
            retrieved_chunks=retrieved_chunks,
            explanation=explanation,
            **_model_response_fields(gen_main),
            diagnostics=diag,
        )

    v = validate_lua_code(code)
    if v.normalized_code:
        code = v.normalized_code

    first_pass_syntax_ok = v.syntax_ok
    iterations = 1
    reflexion_applied = False

    if not v.syntax_ok:
        reflexion_applied = True
        iterations = 2
        review_body = safe_prompt_format(
            REVIEW_REFLEXION_PROMPT_TEMPLATE,
            user_task=task_prompt,
            current_code=code,
            syntax_ok=v.syntax_ok,
            hard_errors_block="\n".join(f"  - {e}" for e in v.hard_errors) or "  (нет)",
            warnings_block="\n".join(f"  - {e}" for e in v.warnings) or "  (нет)",
            hints_block="\n".join(f"  - {e}" for e in v.hints) or "  (нет)",
        )
        review_prompt = f"{system_part}\n\n{review_body}"
        if diag is not None:
            diag["review_prompt_chars"] = len(review_prompt)
        gen_review = await generate_with_infra_fallback(client, review_prompt, call_label="review")
        code_rev = extract_lua_block(gen_review.text)
        if code_rev:
            code = code_rev
            explanation = extract_explanation(gen_review.text) or explanation
            v = validate_lua_code(code)
            if v.normalized_code:
                code = v.normalized_code

    return _base_result(
        "success" if v.syntax_ok else "error",
        code=code,
        message="" if v.syntax_ok else _join_message(v.hard_errors + v.warnings),
        validation=_validation_response(v),
        iterations=iterations,
        first_pass_syntax_ok=first_pass_syntax_ok,
        reflexion_applied=reflexion_applied,
        retrieved_chunks=retrieved_chunks,
        explanation=explanation,
        **_model_response_fields(gen_main),
        diagnostics=diag,
    )


async def run_generate(
    client: httpx.AsyncClient,
    prompt: str,
    context: dict[str, Any] | None,
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    previous_code = _extract_previous_code(context)
    if _should_force_clarification_heuristic(prompt, previous_code):
        clar_prompt = safe_prompt_format(CLARIFICATION_PROMPT_TEMPLATE, prompt=prompt)
        question_gen = await generate_with_infra_fallback(client, clar_prompt, call_label="clarify_question")
        return _base_result(
            "needs_clarification",
            clarifying_question=(question_gen.text or "").strip()[:500],
            **_model_response_fields(question_gen),
        )

    # LLM-router только для узкого класса неясных запросов: иначе лишняя латентность/уточнения.
    if not _looks_like_edit_request(prompt, previous_code):
        lower_prompt = prompt.lower()
        has_domain = _is_domain_grounded(lower_prompt)
        term_count = len(re.findall(r"[\w\u0400-\u04FF]{2,}", lower_prompt))
        router_candidate = (4 <= term_count <= 7) and not has_domain
        if router_candidate:
            try:
                needs_clarification, router_result = await _needs_clarification_llm(client, prompt)
            except Exception as e:
                errs = [f"Ollama недоступен: {e}"]
                return _base_result("error", message=_join_message(errs), validation=_ollama_validation_dict(errs))
            if needs_clarification:
                clar_prompt = safe_prompt_format(CLARIFICATION_PROMPT_TEMPLATE, prompt=prompt)
                question_gen = await generate_with_infra_fallback(client, clar_prompt, call_label="clarify_question")
                return _base_result(
                    "needs_clarification",
                    clarifying_question=(question_gen.text or "").strip()[:500],
                    **_model_response_fields(question_gen),
                )
        else:
            router_result = None
    else:
        router_result = None
    result = await _run_generation_pipeline(
        client,
        task_prompt=prompt,
        user_prompt=prompt,
        previous_code=previous_code,
        include_diagnostics=include_diagnostics,
        context=context,
    )
    if router_result and not result.get("used_model"):
        result.update(_model_response_fields(router_result))
    return result


async def run_edit(
    client: httpx.AsyncClient,
    instruction: str,
    original_code: str,
    *,
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    task_prompt = safe_prompt_format(
        EDIT_REQUEST_TEMPLATE,
        original_code=original_code,
        instruction=instruction,
    )
    return await _run_generation_pipeline(
        client,
        task_prompt=task_prompt,
        user_prompt=instruction,
        previous_code=original_code,
        include_diagnostics=include_diagnostics,
        context=None,
    )
