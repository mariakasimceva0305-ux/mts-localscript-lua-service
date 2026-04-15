#!/usr/bin/env python3
"""
Локальные проверки validator.validate_lua_code (без HTTP).
Требуется luac в PATH (как в Docker-образе api).
Запуск из корня репозитория:
  python tests/test_validator.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path


def _api_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "api"


def main() -> int:
    if not shutil.which("luac"):
        print("SKIP: luac не найден в PATH (ожидается образ api или Lua 5.5+ / LUAC_BIN)")
        return 0

    sys.path.insert(0, str(_api_dir()))
    from validator import validate_lua_code  # noqa: PLC0415

    def case(
        label: str,
        code: str,
        *,
        min_hard: int = 0,
        max_hard: int = 99,
        min_warn: int = 0,
        min_hint: int = 0,
        expect_syntax_ok: bool | None = None,
    ) -> None:
        v = validate_lua_code(code)
        if not (min_hard <= len(v.hard_errors) <= max_hard):
            raise SystemExit(
                f"{label}: expected hard_errors in [{min_hard},{max_hard}], got {v.hard_errors!r}"
            )
        if len(v.warnings) < min_warn:
            raise SystemExit(f"{label}: expected warnings>={min_warn}, got {v.warnings!r}")
        if len(v.hints) < min_hint:
            raise SystemExit(f"{label}: expected hints>={min_hint}, got {v.hints!r}")
        if expect_syntax_ok is not None and v.syntax_ok != expect_syntax_ok:
            raise SystemExit(
                f"{label}: syntax_ok {v.syntax_ok}, expected {expect_syntax_ok}"
            )

    case("syntax_ok return", "return wf.vars.userName", min_hard=0, expect_syntax_ok=True)
    case(
        "wf unknown field is warning not hard",
        "return wf.workflow.id",
        min_hard=0,
        min_warn=1,
        expect_syntax_ok=True,
    )
    case(
        "wf.var typo denylist hard",
        "return wf.var.userName",
        min_hard=1,
        expect_syntax_ok=False,
    )
    case("forbidden os.execute", "os.execute('ls')", min_hard=1, expect_syntax_ok=False)
    case(
        "wf.vars warn no init",
        "return wf.vars.unknown_field",
        min_hard=0,
        min_warn=1,
        expect_syntax_ok=True,
    )
    case(
        "unknown array method",
        "return _utils.array.bogus()",
        min_hard=0,
        min_warn=1,
        expect_syntax_ok=True,
    )
    case(
        "require dynamic warn",
        "return require(x)",
        min_hard=0,
        min_warn=1,
        expect_syntax_ok=True,
    )
    print("OK: all validator cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
