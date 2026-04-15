#!/usr/bin/env python3
"""
Прогон репрезентативного подмножества для сравнения RETRIEVAL_TOP_K / OLLAMA_HTTP_TIMEOUT_S.

Состав (фиксированные id из tests/test_cases.json):
  - heavy four: retrieval_iso_date, repair_*
  - обычные: last_array_element, return_username, conditional_ok_empty
  - clarification: ambiguous_short (ожидается needs_clarification)

Конфигурация сервера (RETRIEVAL_TOP_K, таймауты) задаётся в контейнере api —
перед серией прогонов пересоздайте api с нужным env (см. docs/jury/EMPIRICAL_RUNBOOK.md).

Пример:
  python -u tests/run_representative_subset.py \\
    --base-url http://127.0.0.1:8000 --timeout 720 \\
    --label topk_4_strict --output artifacts/sweep/subset_topk4.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

TARGET_IDS: tuple[str, ...] = (
    "retrieval_iso_date",
    "repair_nested_math",
    "repair_multiline_if",
    "repair_table_literal",
    "last_array_element",
    "return_username",
    "conditional_ok_empty",
    "ambiguous_short",
)


def load_subset(cases_path: Path) -> list[dict[str, Any]]:
    with open(cases_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("cases: ожидается JSON-массив")
    by_id = {str(c.get("id")): c for c in data}
    out: list[dict[str, Any]] = []
    for cid in TARGET_IDS:
        if cid not in by_id:
            raise SystemExit(f"Не найден кейс id={cid!r} в {cases_path}")
        out.append(by_id[cid])
    return out


def _prompt_chars(diag: dict[str, Any] | None) -> int | None:
    if not isinstance(diag, dict):
        return None
    v = diag.get("gen1_prompt_chars")
    return int(v) if v is not None else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parent / "test_cases.json",
    )
    ap.add_argument("--timeout", type=float, default=720.0)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument(
        "--label",
        default="",
        help="Метка прогона (например topk_4, timeout_240_hackathon)",
    )
    args = ap.parse_args()
    url = args.base_url.rstrip("/") + "/generate"
    cases = load_subset(args.cases)
    rows: list[dict[str, Any]] = []

    print(f"URL={url} timeout={args.timeout}s label={args.label!r} cases={len(cases)}")
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for c in cases:
            cid = str(c["id"])
            cat = c.get("category", "")
            t0 = time.perf_counter()
            row: dict[str, Any] = {
                "id": cid,
                "category": cat,
                "expect_clarification": bool(c.get("expect_clarification")),
                "http_status": None,
                "latency_s": None,
                "parsed": None,
                "error": None,
            }
            try:
                r = client.post(
                    url,
                    json={
                        "prompt": c["prompt"],
                        "context": c.get("context"),
                        "include_diagnostics": True,
                    },
                )
            except Exception as e:  # noqa: BLE001
                row["error"] = type(e).__name__ + ": " + str(e)
                row["latency_s"] = round(time.perf_counter() - t0, 4)
                rows.append(row)
                print(f"[{cid}] TRANSPORT {row['error']}")
                continue

            row["http_status"] = r.status_code
            row["latency_s"] = round(time.perf_counter() - t0, 4)
            if r.status_code == 200:
                try:
                    row["parsed"] = r.json()
                except json.JSONDecodeError:
                    row["parse_error"] = r.text[:400]
            else:
                row["body_preview"] = r.text[:400]
            rows.append(row)
            p = row.get("parsed") or {}
            di = p.get("diagnostics") if isinstance(p, dict) else None
            pc = _prompt_chars(di if isinstance(di, dict) else None)
            print(
                f"[{cid}] http={r.status_code} latency={row['latency_s']}s "
                f"status={p.get('status')} syntax_ok="
                f"{(p.get('validation') or {}).get('syntax_ok')} "
                f"gen1_prompt_chars={pc}"
            )

    gen_rows = [
        r
        for r in rows
        if r.get("http_status") == 200
        and isinstance(r.get("parsed"), dict)
        and r["parsed"].get("status") in ("success", "error")
    ]
    clar_rows = [r for r in rows if r.get("expect_clarification")]
    clar_ok = sum(
        1
        for r in clar_rows
        if isinstance(r.get("parsed"), dict)
        and r["parsed"].get("status") == "needs_clarification"
    )
    transport_fail = sum(
        1 for r in rows if r.get("http_status") != 200 or not r.get("parsed")
    )
    latencies = [float(r["latency_s"]) for r in rows if r.get("latency_s") is not None]
    prompt_chars = [
        _prompt_chars(
            (r.get("parsed") or {}).get("diagnostics")
            if isinstance(r.get("parsed"), dict)
            else None
        )
        for r in gen_rows
    ]
    prompt_chars_n = [x for x in prompt_chars if x is not None]

    summary = {
        "label": args.label or None,
        "base_url": args.base_url,
        "cases_n": len(rows),
        "transport_failed": transport_fail,
        "generation_cases": len(gen_rows),
        "success_count": sum(
            1 for r in gen_rows if r["parsed"].get("status") == "success"
        ),
        "syntax_ok_count": sum(
            1
            for r in gen_rows
            if (r["parsed"].get("validation") or {}).get("syntax_ok") is True
        ),
        "expect_clarification_hits": clar_ok,
        "expect_clarification_n": len(clar_rows),
        "avg_latency_s": round(statistics.mean(latencies), 4) if latencies else None,
        "p50_latency_s": round(statistics.median(latencies), 4) if latencies else None,
        "avg_gen1_prompt_chars": round(statistics.mean(prompt_chars_n), 1)
        if prompt_chars_n
        else None,
    }

    report: dict[str, Any] = {
        "meta": {
            "script": "run_representative_subset.py",
            "note": "Параметры RETRIEVAL_TOP_K и OLLAMA_HTTP_TIMEOUT_S — на стороне сервера; "
            "сверяйте docker exec lua-gen-api printenv …",
        },
        "summary": summary,
        "runs": rows,
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.output}")
    print("\nSUMMARY:", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
