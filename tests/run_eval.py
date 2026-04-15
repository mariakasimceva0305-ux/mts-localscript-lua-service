#!/usr/bin/env python3
"""
Eval framework: POST /generate по набору кейсов, метрики и отчёт.

Требуется запущенный API. Конфигурация (RETRIEVAL_TOP_K, MODEL_NAME, …) задаётся
на стороне сервера — для сравнения двух конфигураций перезапустите api с разным .env
и сохраните два отчёта (--output).

Примеры:
  python tests/run_eval.py
  python tests/run_eval.py --cases tests/test_cases.json
  python tests/run_eval.py --cases a.json --cases b.json
  python tests/run_eval.py --type generate,edit
  python tests/run_eval.py --output eval_report.json --label baseline
  python tests/run_eval.py --quiet --output summary.json
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE = os.environ.get("EVAL_API_URL", "http://127.0.0.1:8000")

CATEGORIES = frozenset(
    {"generate", "edit", "clarification", "retrieval_heavy", "repair_heavy"}
)


def infer_category(case: dict[str, Any]) -> str:
    if case.get("category") in CATEGORIES:
        return str(case["category"])
    if case.get("expect_clarification"):
        return "clarification"
    ctx = case.get("context")
    if isinstance(ctx, dict) and any(
        ctx.get(k) for k in ("previous_code", "code", "lua", "script")
    ):
        return "edit"
    return "generate"


def load_cases(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit(f"{path}: ожидается JSON-массив кейсов")
    for c in data:
        if "prompt" not in c:
            raise SystemExit(f"{path}: у кейса {c.get('id')} нет prompt")
        c["_category"] = infer_category(c)
    return data


def env_snapshot() -> dict[str, str | None]:
    keys = (
        "RETRIEVAL_TOP_K",
        "MODEL_NAME",
        "FALLBACK_MODEL",
        "RETRIEVAL_DEBUG",
        "OLLAMA_BASE_URL",
        "CONTEXT_SIZE",
        "OLLAMA_NUM_PREDICT",
        "OLLAMA_HTTP_TIMEOUT_S",
    )
    return {k: os.environ.get(k) for k in keys}


def filter_cases(
    cases: list[dict[str, Any]], types: set[str] | None
) -> list[dict[str, Any]]:
    if not types:
        return cases
    return [c for c in cases if c.get("_category") in types]


def _reflexion_attempted(parsed: dict[str, Any]) -> bool:
    if parsed.get("reflexion_applied") is True:
        return True
    return int(parsed.get("iterations") or 1) >= 2


def _first_pass_syntax_bad(parsed: dict[str, Any]) -> bool:
    fp = parsed.get("first_pass_syntax_ok")
    if fp is not None:
        return fp is False
    # Старый API без поля: второй проход подразумевает, что первый не syntax_ok.
    return _reflexion_attempted(parsed)


def _final_syntax_ok(parsed: dict[str, Any]) -> bool:
    return (parsed.get("validation") or {}).get("syntax_ok") is True


def _final_generation_success(parsed: dict[str, Any]) -> bool:
    return parsed.get("status") == "success"


def _hard_error_count(parsed: dict[str, Any]) -> int:
    val = parsed.get("validation") or {}
    he = val.get("hard_errors")
    if isinstance(he, list):
        return len(he)
    return 0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    http_fail = sum(1 for r in rows if r.get("http_status") != 200)
    ok_body = [r for r in rows if r.get("http_status") == 200 and r.get("parsed")]

    by_status = Counter(str(r["parsed"].get("status", "")) for r in ok_body)
    clar = sum(1 for r in ok_body if r["parsed"].get("status") == "needs_clarification")
    gen_rows = [
        r
        for r in ok_body
        if r["parsed"].get("status") in ("success", "error")
    ]

    success = sum(1 for r in gen_rows if r["parsed"].get("status") == "success")
    syntax_ok = sum(
        1
        for r in gen_rows
        if (r["parsed"].get("validation") or {}).get("syntax_ok") is True
    )
    repair_attempts = [
        r for r in gen_rows if int(r["parsed"].get("iterations", 1)) >= 2
    ]
    review_attempt_rows = [r for r in gen_rows if _reflexion_attempted(r["parsed"])]
    review_helped_rows = [
        r
        for r in review_attempt_rows
        if _first_pass_syntax_bad(r["parsed"])
        and _final_syntax_ok(r["parsed"])
        and _final_generation_success(r["parsed"])
    ]
    review_no_help_rows = [
        r
        for r in review_attempt_rows
        if _first_pass_syntax_bad(r["parsed"])
        and not (
            _final_syntax_ok(r["parsed"]) and _final_generation_success(r["parsed"])
        )
    ]
    still_bad_rows = [
        r
        for r in gen_rows
        if not _final_generation_success(r["parsed"])
        or not _final_syntax_ok(r["parsed"])
    ]
    transport_failed_rows = [
        r
        for r in rows
        if r.get("http_status") != 200 or not r.get("parsed")
    ]
    repair_ok = sum(
        1
        for r in repair_attempts
        if (r["parsed"].get("validation") or {}).get("syntax_ok") is True
    )

    latencies = [float(r["latency_s"]) for r in rows if r.get("latency_s") is not None]
    fb = sum(
        1
        for r in ok_body
        if r["parsed"].get("fallback_used") is True
    )
    models = Counter(
        str(r["parsed"].get("used_model") or "unknown")
        for r in ok_body
        if r["parsed"].get("status") != "needs_clarification"
    )

    exp_rows = [r for r in rows if r.get("expect_clarification")]
    exp_hits = sum(
        1
        for r in exp_rows
        if r.get("parsed") and r["parsed"].get("status") == "needs_clarification"
    )
    exp_hit_rate = (exp_hits / len(exp_rows)) if exp_rows else None

    gen_n = len(gen_rows)
    ra_n = len(review_attempt_rows)
    rh_n = len(review_helped_rows)
    out: dict[str, Any] = {
        "total_cases": n,
        "http_non_200": http_fail,
        "responses_parsed": len(ok_body),
        "by_status": dict(by_status),
        "clarification_count": clar,
        "clarification_rate": (clar / n) if n else 0.0,
        "expect_clarification_cases": len(exp_rows),
        "expect_clarification_hits": exp_hits,
        "expect_clarification_hit_rate": exp_hit_rate,
        "generation_cases": gen_n,
        "success_count": success,
        "success_rate": (success / gen_n) if gen_n else 0.0,
        "syntax_ok_count": syntax_ok,
        "syntax_ok_rate": (syntax_ok / gen_n) if gen_n else 0.0,
        "syntax_first_pass_count": sum(
            1
            for r in gen_rows
            if (r["parsed"].get("validation") or {}).get("syntax_ok")
            and int(r["parsed"].get("iterations", 1)) == 1
        ),
        # repair_* — как раньше (iterations>=2 и syntax_ok после любого числа проходов)
        "repair_attempted_count": len(repair_attempts),
        "repair_success_count": repair_ok,
        "repair_success_rate": (repair_ok / len(repair_attempts))
        if repair_attempts
        else None,
        # review_* — reflexion: первый проход с syntax_ok=false, второй проход, итог success+syntax_ok
        "review_attempted_count": ra_n,
        "review_helped_count": rh_n,
        "review_used_rate": (rh_n / ra_n) if ra_n else None,
        "review_coverage_rate": (ra_n / gen_n) if gen_n else 0.0,
        "reflexion_fixed_case_ids": [str(r["id"]) for r in review_helped_rows],
        "reflexion_no_help_case_ids": [str(r["id"]) for r in review_no_help_rows],
        "still_failing_case_ids": [str(r["id"]) for r in still_bad_rows],
        "transport_failed_case_ids": [str(r["id"]) for r in transport_failed_rows],
        "iterations2_improved_case_ids": [str(r["id"]) for r in review_helped_rows],
        "top5_weak_case_ids": [
            str(r["id"])
            for r in sorted(
                still_bad_rows,
                key=lambda x: (
                    _hard_error_count(x["parsed"]),
                    float(x.get("latency_s") or 0.0),
                ),
                reverse=True,
            )[:5]
        ],
        "fallback_used_count": fb,
        "fallback_used_rate": (fb / len(ok_body)) if ok_body else 0.0,
        "used_model_distribution": dict(models),
        "avg_latency_s": statistics.mean(latencies) if latencies else None,
        "p50_latency_s": statistics.median(latencies) if latencies else None,
    }

    by_cat: dict[str, dict[str, Any]] = {}
    for cat in CATEGORIES:
        cat_rows = [r for r in rows if r.get("category") == cat]
        if not cat_rows:
            by_cat[cat] = {"n": 0}
            continue
        sub = [r for r in cat_rows if r.get("http_status") == 200 and r.get("parsed")]
        transport_or_parse_fail = len(cat_rows) - len(sub)
        g = [r for r in sub if r["parsed"].get("status") in ("success", "error")]
        g_lat = [float(r["latency_s"]) for r in cat_rows if r.get("latency_s") is not None]
        by_cat[cat] = {
            "n": len(cat_rows),
            "http_200_parsed": len(sub),
            "transport_or_parse_fail": transport_or_parse_fail,
            "success": sum(1 for r in g if r["parsed"].get("status") == "success"),
            "syntax_ok": sum(
                1
                for r in g
                if (r["parsed"].get("validation") or {}).get("syntax_ok") is True
            ),
            "repair_attempts": sum(
                1 for r in g if int(r["parsed"].get("iterations", 1)) >= 2
            ),
            "review_attempted": sum(1 for r in g if _reflexion_attempted(r["parsed"])),
            "review_helped": sum(1 for r in g if r in review_helped_rows),
            "clarification": sum(
                1 for r in sub if r["parsed"].get("status") == "needs_clarification"
            ),
            "avg_latency_s": statistics.mean(g_lat) if g_lat else None,
            "p50_latency_s": statistics.median(g_lat) if g_lat else None,
        }
    out["by_category"] = by_cat
    return out


def print_summary(
    summary: dict[str, Any],
    *,
    baseline: dict[str, Any] | None = None,
) -> None:
    print("\n" + "=" * 60)
    print("EVAL SUMMARY (ключевые метрики)")
    print("=" * 60)
    keys_order = [
        "total_cases",
        "success_rate",
        "syntax_ok_rate",
        "repair_attempted_count",
        "review_attempted_count",
        "review_used_rate",
        "clarification_rate",
        "fallback_used_count",
        "used_model_distribution",
        "avg_latency_s",
        "p50_latency_s",
    ]
    for k in keys_order:
        if k in summary:
            print(f"  {k}: {summary[k]}")
    print("\n  reflexion_fixed_case_ids:", summary.get("reflexion_fixed_case_ids"))
    print("  reflexion_no_help_case_ids:", summary.get("reflexion_no_help_case_ids"))
    print("  still_failing_case_ids:", summary.get("still_failing_case_ids"))
    print("  transport_failed_case_ids:", summary.get("transport_failed_case_ids"))
    print("  iterations2_improved_case_ids:", summary.get("iterations2_improved_case_ids"))
    print("  top5_weak_case_ids:", summary.get("top5_weak_case_ids"))

    print("\n" + "-" * 60)
    print("Полный summary (включая вспомогательные поля)")
    print("-" * 60)
    for k, v in summary.items():
        if k == "by_category":
            print("\nby_category:")
            for ck, cv in v.items():
                print(f"  [{ck}] {cv}")
        else:
            print(f"  {k}: {v}")
    print("=" * 60)

    if baseline and isinstance(baseline.get("summary"), dict):
        bs = baseline["summary"]
        print("\nСравнение с baseline-отчётом (--baseline-report):")
        for key in (
            "success_rate",
            "syntax_ok_rate",
            "repair_attempted_count",
            "review_attempted_count",
            "review_used_rate",
        ):
            if key not in summary:
                continue
            b = bs.get(key)
            c = summary.get(key)
            if b is None and c is None:
                continue
            print(f"  {key}: baseline={b!r} current={c!r}")

    # Краткие выводы о слабых местах (эвристика по метрикам)
    notes: list[str] = []
    if summary.get("generation_cases", 0) > 0:
        sr = float(summary.get("success_rate") or 0)
        sy = float(summary.get("syntax_ok_rate") or 0)
        if sy < sr - 0.05:
            notes.append(
                "syntax_ok заметно ниже success — возможны ошибки валидации при status=success (проверьте ответы)."
            )
        if sy < 0.5:
            notes.append(
                "Низкий syntax_ok_rate — модель или промпт; смотрите review_used_rate и примеры hard_errors."
            )
        rr = summary.get("review_used_rate")
        if (
            rr is not None
            and float(rr) < 0.5
            and (summary.get("review_attempted_count") or 0) >= 2
        ):
            notes.append(
                "Reflexion (второй проход) часто не доводит до syntax_ok — усилить review-промпт или контекст."
            )
        if float(summary.get("fallback_used_rate") or 0) > 0.2:
            notes.append(
                "Высокий fallback_used_rate — проверьте доступность основной модели и сеть к Ollama."
            )
    if notes:
        print("\nHeuristic quality notes:")
        for n in notes:
            print(" -", n)
    else:
        print("\nHeuristic quality notes: (none — метрики в норме или мало данных)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Eval harness для POST /generate")
    ap.add_argument("--base-url", default=DEFAULT_BASE, help="Базовый URL API")
    ap.add_argument(
        "--cases",
        action="append",
        type=Path,
        default=None,
        help="JSON с кейсами (массив объектов). Можно указать несколько раз для объединения наборов.",
    )
    ap.add_argument(
        "--type",
        type=str,
        default="",
        help=f"Фильтр категорий через запятую: {','.join(sorted(CATEGORIES))}",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=420.0,
        help="Таймаут HTTP на кейс (сек). Для reflexion два вызова Ollama — берите запас.",
    )
    ap.add_argument("--output", type=Path, help="Полный JSON-отчёт (runs + summary)")
    ap.add_argument(
        "--jsonl",
        type=Path,
        help="Дополнительно дописать одну строку JSON на кейс",
    )
    ap.add_argument("--label", type=str, default="", help="Метка прогона в отчёте")
    ap.add_argument("--quiet", "-q", action="store_true", help="Только summary в конце")
    ap.add_argument(
        "--baseline-report",
        type=Path,
        default=None,
        help="JSON отчёт прошлого прогона (поле summary) для краткого сравнения метрик",
    )
    args = ap.parse_args()

    default_cases = Path(__file__).resolve().parent / "test_cases.json"
    case_paths = args.cases if args.cases else [default_cases]
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for p in case_paths:
        batch = load_cases(p)
        for c in batch:
            cid = str(c.get("id", ""))
            if cid and cid in seen_ids:
                raise SystemExit(f"Дублирующийся id кейса: {cid}")
            if cid:
                seen_ids.add(cid)
        cases.extend(batch)
    type_filter: set[str] | None = None
    if args.type.strip():
        type_filter = {t.strip() for t in args.type.split(",") if t.strip()}
        bad = type_filter - CATEGORIES
        if bad:
            raise SystemExit(f"Неизвестные категории: {bad}")
    cases = filter_cases(cases, type_filter)

    url = args.base_url.rstrip("/") + "/generate"
    rows: list[dict[str, Any]] = []

    if not args.quiet:
        print(f"Cases files: {[str(p) for p in case_paths]}")
        print(f"Filtered cases: {len(cases)}  URL: {url}")
        print("Client env snapshot (сервер может игнорировать):", json.dumps(env_snapshot(), ensure_ascii=False))

    # trust_env=False: на Windows системный HTTP(S)_PROXY часто ломает POST на 127.0.0.1 (пустой 503).
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for case in cases:
            cid = case.get("id", "?")
            cat = case.get("_category", "generate")
            prompt = case["prompt"]
            ctx = case.get("context")
            t0 = time.perf_counter()
            try:
                r = client.post(url, json={"prompt": prompt, "context": ctx})
            except Exception as e:  # noqa: BLE001
                row = {
                    "id": cid,
                    "category": cat,
                    "expect_clarification": bool(case.get("expect_clarification")),
                    "http_status": None,
                    "error": str(e),
                    "latency_s": time.perf_counter() - t0,
                    "parsed": None,
                }
                rows.append(row)
                if not args.quiet:
                    print(f"[{cid}] TRANSPORT_ERROR {e}")
                continue

            dt = time.perf_counter() - t0
            row: dict[str, Any] = {
                "id": cid,
                "category": cat,
                "expect_clarification": bool(case.get("expect_clarification")),
                "http_status": r.status_code,
                "latency_s": round(dt, 4),
                "parsed": None,
            }
            if r.status_code == 200:
                try:
                    row["parsed"] = r.json()
                except json.JSONDecodeError:
                    row["parse_error"] = r.text[:500]
            else:
                row["body_preview"] = r.text[:300]

            rows.append(row)

            if args.jsonl:
                args.jsonl.parent.mkdir(parents=True, exist_ok=True)
                with open(args.jsonl, "a", encoding="utf-8") as jf:
                    jf.write(json.dumps(row, ensure_ascii=False) + "\n")

            if args.quiet:
                continue

            if r.status_code != 200:
                print(f"[{cid}] HTTP {r.status_code}")
                continue
            data = row["parsed"] or {}
            st = data.get("status")
            val = data.get("validation") or {}
            syn = val.get("syntax_ok")
            it = data.get("iterations", 1)
            um = data.get("used_model")
            fb = data.get("fallback_used")
            print(
                f"[{cid}] {cat:18} status={st} syntax_ok={syn} iters={it} "
                f"model={um!r} fallback={fb} {dt:.2f}s"
            )

    summary = summarize(rows)
    baseline: dict[str, Any] | None = None
    if args.baseline_report:
        try:
            with open(args.baseline_report, encoding="utf-8") as bf:
                baseline = json.load(bf)
        except OSError as e:
            print(f"Warning: не удалось прочитать baseline-report: {e}", file=sys.stderr)

    report = {
        "label": args.label or None,
        "cases_files": [str(p.resolve()) for p in case_paths],
        "type_filter": sorted(type_filter) if type_filter else None,
        "base_url": args.base_url,
        "client_env": env_snapshot(),
        "summary": summary,
        "runs": rows,
        "baseline_report_path": str(args.baseline_report.resolve())
        if args.baseline_report
        else None,
    }

    print_summary(summary, baseline=baseline)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nWrote report: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
