"""Синтаксис: luac -p (Lua 5.5 в образе api); доменные правила Octapi/Low-Code — hard_errors / warnings / hints."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


FORBIDDEN_PATTERNS = [
    (r"\bos\.execute\s*\(", "os.execute"),
    (r"\bio\.popen\s*\(", "io.popen"),
    (r"\bio\.open\s*\(", "io.open"),
    (r"\bio\.lines\s*\(", "io.lines"),
    (r"\bio\.input\s*\(", "io.input"),
    (r"\bio\.output\s*\(", "io.output"),
    (r"\bdebug\.", "debug.*"),
    (r"\bdofile\s*\(", "dofile"),
    (r"\bloadfile\s*\(", "loadfile"),
    (r"\bloadstring\s*\(", "loadstring"),
    (r"\bload\s*\(\s*['\"]", "load('...') динамической загрузки кода"),
]

WF_VARS_READ = re.compile(r"\bwf\.vars\.([a-zA-Z_][a-zA-Z0-9_]*)")
WF_VARS_WRITE = re.compile(r"wf\.vars\.([a-zA-Z_][a-zA-Z0-9_]*)\s*=")
WF_BAD_SUBFIELD = re.compile(r"\bwf\.([a-zA-Z_][a-zA-Z0-9_]*)\b")
# Только явный denylist → hard_error; прочие неизвестные wf.<x> → warning (избегаем ложных отказов).
WF_SUBFIELD_HARD_DENY = frozenset(
    {
        "var",  # типичная опечатка wf.vars
        "execute",
        "eval",
        "load",
        "loadfile",
        "dofile",
        "debug",
        "os",
        "io",
    }
)
UTILS_ARRAY_CALL = re.compile(r"\b_utils\.array\.(\w+)\s*\(")
UTILS_ARRAY_ALLOWED = frozenset({"new", "markAsArray"})
RETURN_LINE = re.compile(r"^\s*return\b")


@dataclass
class ValidationResult:
    """hard_errors — блокируют syntax_ok и триггерят второй проход (reflexion); warnings/hints — нет."""

    syntax_ok: bool
    hard_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    normalized_code: str | None = None

    @property
    def errors(self) -> list[str]:
        """Плоский список для обратной совместимости (hard → warn → hint)."""
        return self.hard_errors + self.warnings + self.hints


def validation_to_api_dict(v: ValidationResult) -> dict[str, Any]:
    return {
        "syntax_ok": v.syntax_ok,
        "hard_errors": list(v.hard_errors),
        "warnings": list(v.warnings),
        "hints": list(v.hints),
        "errors": v.errors,
    }


# Типичные пути после make install из исходников Lua (Dockerfile) — до поиска по PATH.
_FALLBACK_LUAC_PATHS: tuple[str, ...] = (
    "/usr/local/bin/luac",
    "/usr/bin/luac",
)


def _resolve_luac_cmd() -> list[str] | None:
    candidates: list[str] = []
    env_cmd = (os.environ.get("LUAC_BIN") or "").strip()
    if env_cmd:
        candidates.append(env_cmd)
    candidates.extend(_FALLBACK_LUAC_PATHS)
    for name in ("luac5.5", "luac", "luac5.3"):
        found = shutil.which(name)
        if found:
            candidates.append(found)

    seen: set[str] = set()
    for exe in candidates:
        if not exe or exe in seen:
            continue
        seen.add(exe)
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return [exe, "-p", "-"]
    return None


def _run_luac(code: str) -> tuple[bool, str, bool]:
    cmd = _resolve_luac_cmd()
    if cmd is None:
        return True, "", True
    try:
        proc = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        err = (proc.stderr or "").strip()
        return proc.returncode == 0, err, False
    except FileNotFoundError:
        return True, "", True
    except subprocess.TimeoutExpired:
        return False, "luac: timeout", False


def _try_implicit_return_variant(code: str) -> tuple[str | None, bool]:
    stripped = code.strip()
    if not stripped or re.match(r"^\s*return\b", stripped):
        return None, False

    if "\n" not in stripped and ";" not in stripped:
        candidate = f"return {stripped}"
        ok, _, skipped = _run_luac(candidate)
        if skipped:
            return None, False
        if ok:
            return candidate, True

    lines = [ln.strip() for ln in stripped.splitlines() if ln.strip()]
    if len(lines) == 1:
        candidate = f"return {lines[0]}"
        ok, _, skipped = _run_luac(candidate)
        if skipped:
            return None, False
        if ok:
            return candidate, True

    return None, False


def _check_wf_namespace(
    code: str, hard_errors: list[str], warnings: list[str]
) -> None:
    seen: set[str] = set()
    for m in WF_BAD_SUBFIELD.finditer(code):
        sub = m.group(1)
        if sub in ("vars", "initVariables"):
            continue
        if sub in seen:
            continue
        seen.add(sub)
        if sub in WF_SUBFIELD_HARD_DENY:
            hard_errors.append(
                f"wf.{sub}: явный denylist запрещённых/опасных полей wf.* (см. WF_SUBFIELD_HARD_DENY в validator.py)"
            )
        else:
            warnings.append(
                f"Неизвестное поле wf.{sub}: в baseline документированы только wf.vars и wf.initVariables; "
                "при появлении официального API — проверьте актуальную документацию Octapi"
            )


def _check_utils_array(code: str, warnings: list[str], hints: list[str]) -> None:
    if re.search(r"\barray\.(new|markAsArray)\s*\(", code):
        if not re.search(r"_utils\.array\.(new|markAsArray)\s*\(", code):
            hints.append(
                "Вызов array.new / markAsArray без префикса _utils.array — проверьте API платформы"
            )
    for m in UTILS_ARRAY_CALL.finditer(code):
        name = m.group(1)
        if name not in UTILS_ARRAY_ALLOWED:
            warnings.append(
                f"Неизвестный метод _utils.array.{name}() — сверьте с документацией (ожидаются new, markAsArray)"
            )


def _check_return_patterns(code: str, hints: list[str]) -> None:
    lines = code.splitlines()
    ret_lines = [i for i, ln in enumerate(lines) if RETURN_LINE.search(ln)]
    if len(ret_lines) >= 2:
        hints.append(
            "Несколько операторов return: убедитесь, что в Low-Code достигается нужная ветка"
        )
    if re.search(r"\breturn\b.*;\s*\S", code.replace("\n", " ")[:800]):
        hints.append(
            "После return на той же строке есть ещё код через «;» — возможно, мёртвый код"
        )


def _check_antipatterns(code: str, hints: list[str]) -> None:
    if re.search(r"\bwhile\s+true\b", code):
        hints.append("while true без явного выхода — риск бесконечного цикла в сценарии")
    if re.search(r"\bgetfenv\b|\bsetfenv\b", code):
        hints.append("getfenv/setfenv — нетипично для изолированных сценариев Octapi")
    if re.search(r"\brequire\s*\(", code):
        hints.append("require() в пользовательском скрипте может быть недоступен в среде Low-Code")


def _check_require_dynamic(code: str, warnings: list[str]) -> None:
    if re.search(r"\brequire\s*\(\s*[^'\"]", code):
        warnings.append("require с нестроковым аргументом — подозрительно для статического анализа")


def validate_lua_code(code: str) -> ValidationResult:
    hard_errors: list[str] = []
    warnings: list[str] = []
    hints: list[str] = []
    normalized: str | None = None

    for pattern, name in FORBIDDEN_PATTERNS:
        if re.search(pattern, code):
            hard_errors.append(f"Запрещённый или опасный вызов: {name}")

    _check_wf_namespace(code, hard_errors, warnings)
    _check_utils_array(code, warnings, hints)
    _check_return_patterns(code, hints)
    _check_antipatterns(code, hints)
    _check_require_dynamic(code, warnings)

    ok, stderr, skipped = _run_luac(code)
    if skipped:
        luac_ok = True
        hints.append(
            "Проверка luac пропущена: бинарник не найден (установите Lua 5.5+ или задайте LUAC_BIN)"
        )
    elif ok:
        luac_ok = True
    else:
        alt, alt_ok = _try_implicit_return_variant(code)
        if alt_ok and alt is not None:
            luac_ok = True
            normalized = alt
        else:
            luac_ok = False
            if stderr:
                hard_errors.append(f"Синтаксис Lua: {stderr}")

    reads = set(WF_VARS_READ.findall(code))
    writes = set(WF_VARS_WRITE.findall(code))
    for name in reads:
        if name not in writes and f"initVariables.{name}" not in code:
            warnings.append(
                f"wf.vars.{name} читается без явной инициализации в этом скрипте (нет присваивания и initVariables.{name})"
            )

    syntax_ok = luac_ok and len(hard_errors) == 0

    return ValidationResult(
        syntax_ok=syntax_ok,
        hard_errors=hard_errors,
        warnings=warnings,
        hints=hints,
        normalized_code=normalized,
    )


def validation_errors_for_repair(v: ValidationResult) -> list[str]:
    """Только hard_errors — repair не запускается из-за warnings/hints."""
    return list(v.hard_errors)
