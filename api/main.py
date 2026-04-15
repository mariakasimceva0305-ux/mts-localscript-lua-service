"""FastAPI: POST /generate — генерация Lua для MWS Octapi через локальный Ollama."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AliasChoices, BaseModel, Field

from orchestrator import run_edit, run_generate
from retriever import list_docs_snippets, retrieve_for_generation
from validator import validate_lua_code, validation_to_api_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
CAT_RUNNER_PNG = STATIC_DIR / "media" / "cat_runner.png"


def _ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434").rstrip("/")


def _ollama_base_url_candidates() -> list[str]:
    primary = _ollama_base_url()
    out: list[str] = [primary]
    if "://ollama:11434" in primary:
        out.extend(
            [
                primary.replace("://ollama:11434", "://127.0.0.1:11434"),
                primary.replace("://ollama:11434", "://localhost:11434"),
                primary.replace("://ollama:11434", "://host.docker.internal:11434"),
            ]
        )
    return list(dict.fromkeys(out))


def _model_names() -> tuple[str, str]:
    return (
        os.environ.get("MODEL_NAME", "qwen2.5-coder:7b").strip(),
        os.environ.get("FALLBACK_MODEL", "deepseek-coder:6.7b").strip(),
    )


async def readiness_payload(client: httpx.AsyncClient) -> dict[str, Any]:
    """Сводка для /ready и лога старта (без изменения контракта /generate)."""
    base = _ollama_base_url()
    primary, fallback = _model_names()
    out: dict[str, Any] = {
        "ready": False,
        "ollama_reachable": False,
        "ollama_base_url": base,
        "primary_model": primary,
        "primary_available": False,
        "fallback_model": fallback,
        "fallback_available": False,
        "models_in_ollama": [],
        "detail": "",
    }
    data: dict[str, Any] | None = None
    last_error: Exception | None = None
    used_base = base
    for candidate in _ollama_base_url_candidates():
        try:
            r = await client.get(f"{candidate}/api/tags", timeout=8.0)
            r.raise_for_status()
            data = r.json()
            used_base = candidate
            break
        except Exception as e:  # noqa: PERF203
            last_error = e
            continue
    if data is None:
        out["detail"] = f"Ollama недоступен по HTTP: {last_error or ''}"
        return out

    out["ollama_reachable"] = True
    out["ollama_base_url"] = used_base
    names: list[str] = []
    for m in data.get("models") or []:
        n = m.get("name")
        if isinstance(n, str) and n:
            names.append(n)
    out["models_in_ollama"] = names

    out["primary_available"] = primary in names
    out["fallback_available"] = fallback in names
    out["ready"] = out["primary_available"] or out["fallback_available"]
    if not out["ready"]:
        out["detail"] = (
            f"В Ollama нет ни основной ({primary}), ни запасной ({fallback}) модели. "
            "Проверьте логи сервиса ollama-pull и сеть при первом pull."
        )
    return out


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        app.state.http = client
        primary, fb = _model_names()
        base = _ollama_base_url()
        logger.info(
            "=== lua-gen-api startup: OLLAMA_BASE_URL=%s MODEL_NAME=%s FALLBACK_MODEL=%s ===",
            base,
            primary,
            fb,
        )
        snap = await readiness_payload(client)
        logger.info("Startup readiness: %s", json.dumps(snap, ensure_ascii=False))
        if not snap.get("ready"):
            logger.warning(
                "Сервис поднят, но готовность к инференсу не подтверждена — см. GET /ready "
                "(ollama-pull мог не завершиться или модели не совпали с MODEL_NAME/FALLBACK_MODEL)."
            )
        else:
            logger.info(
                "POST /generate готов: Ollama доступен и есть хотя бы одна из моделей (primary=%s, fallback=%s).",
                snap.get("primary_available"),
                snap.get("fallback_available"),
            )
        yield


app = FastAPI(title="Lua Low-Code Generator", version="0.1.0", lifespan=lifespan)


class GenerateBody(BaseModel):
    prompt: str = Field(..., min_length=1, description="Текст задачи (RU/EN)")
    context: dict[str, Any] | None = Field(default=None, description="Опционально: previous_code, уточнения")
    include_diagnostics: bool = Field(
        default=False,
        description="Если true — в ответе поле diagnostics (размеры промптов, retrieval, этапы).",
    )


class GenerateResponse(BaseModel):
    status: str
    code: str
    clarifying_question: str = ""
    message: str = ""
    validation: dict[str, Any]
    iterations: int
    retrieval_debug: list[dict[str, Any]] | None = None
    used_model: str | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    # Reflexion: после первого прохода; None если до валидации Lua не дошли
    first_pass_syntax_ok: bool | None = None
    reflexion_applied: bool = False
    diagnostics: dict[str, Any] | None = None
    retrieved_chunks: list[dict[str, Any]] = []
    explanation: str = ""


class EditBody(BaseModel):
    instruction: str = Field(..., min_length=1)
    original_code: str = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices(
            "original_code",
            "code",
            "current_code",
            "originalCode",
            "currentCode",
        ),
    )
    include_diagnostics: bool = False


class ValidateBody(BaseModel):
    code: str = Field(..., min_length=1)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/models")
async def models_config():
    """Текущие имена моделей из env (без вызова Ollama)."""
    primary, fb = _model_names()
    return {
        "ollama_base_url": _ollama_base_url(),
        "model_name": primary,
        "fallback_model": fb,
        "fallback_policy": (
            "Сначала всегда model_name; fallback_model только при инфраструктурной ошибке "
            "(сеть, таймаут, 5xx/404 HTTP, JSON Ollama с полем error). "
            "Не используется из-за ошибки валидации Lua или отсутствия ```lua."
        ),
    }


@app.get("/retrieve/debug")
async def retrieve_debug(q: str, extra: str = ""):
    """Отладка retrieval (BM25 + keyword) без вызова LLM."""
    return retrieve_for_generation(q, extra, log=False)


@app.get("/docs-snippets")
async def docs_snippets():
    return {"items": list_docs_snippets()}


@app.get("/ready")
async def ready(request: Request):
    """Readiness: Ollama HTTP и наличие хотя бы одной из MODEL_NAME / FALLBACK_MODEL."""
    client: httpx.AsyncClient = request.app.state.http
    body = await readiness_payload(client)
    status = 200 if body.get("ready") else 503
    return JSONResponse(status_code=status, content=body)


@app.post("/generate", response_model=GenerateResponse)
async def generate_endpoint(body: GenerateBody, request: Request):
    client: httpx.AsyncClient = request.app.state.http
    try:
        result = await run_generate(
            client,
            body.prompt,
            body.context,
            include_diagnostics=body.include_diagnostics,
        )
    except Exception as e:
        logger.exception("generate failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return GenerateResponse(**result)


@app.post("/edit", response_model=GenerateResponse)
async def edit_endpoint(body: EditBody, request: Request):
    client: httpx.AsyncClient = request.app.state.http
    try:
        result = await run_edit(
            client,
            instruction=body.instruction,
            original_code=body.original_code,
            include_diagnostics=body.include_diagnostics,
        )
    except Exception as e:
        logger.exception("edit failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
    return GenerateResponse(**result)


@app.post("/validate")
async def validate_endpoint(body: ValidateBody):
    v = validate_lua_code(body.code)
    return {"status": "ok" if v.syntax_ok else "error", "validation": validation_to_api_dict(v)}


@app.get("/media/cat_runner.png", include_in_schema=False)
async def serve_cat_runner_png():
    """Прямая ссылка на PNG маскота (тот же файл, что в полоске UI)."""
    if not CAT_RUNNER_PNG.is_file():
        raise HTTPException(status_code=404, detail="Нет файла static/media/cat_runner.png")
    return FileResponse(CAT_RUNNER_PNG, media_type="image/png", filename="cat_runner.png")


@app.get("/cat", response_class=HTMLResponse, include_in_schema=False)
async def cat_preview_page():
    """Страница-превью: по ссылке сразу видно картинку маскота."""
    if not CAT_RUNNER_PNG.is_file():
        return HTMLResponse(
            content=(
                "<!doctype html><html lang=ru><meta charset=utf-8>"
                "<title>Маскот</title><body style=font-family:system-ui;padding:24px>"
                "<p>Файл <code>static/media/cat_runner.png</code> не найден на сервере.</p>"
                "</body></html>"
            ),
            status_code=404,
        )
    return HTMLResponse(
        content="""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Маскот LocalScript</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f5f5f5; color: #1a1a1a; }
    .box { max-width: 520px; margin: 0 auto; background: #fff; padding: 20px; border-radius: 12px;
            border: 1px solid #dedede; text-align: center; }
    img { max-width: 100%; height: auto; max-height: 72vh; vertical-align: bottom; }
    p, a { font-size: 14px; }
    code { font-size: 13px; }
  </style>
</head>
<body>
  <div class="box">
    <p>Тот же PNG, что в полоске над чатом.</p>
    <p><code>/media/cat_runner.png</code></p>
    <p><img src="/media/cat_runner.png" alt="Маскот LocalScript"/></p>
    <p><a href="/">← В интерфейс</a></p>
  </div>
</body>
</html>""",
        status_code=200,
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
