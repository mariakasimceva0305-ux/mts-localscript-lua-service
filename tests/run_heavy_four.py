#!/usr/bin/env python3
"""Прогон 4 тяжёлых кейсов с diagnostics (POST /generate)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

TARGET_IDS = frozenset(
    {
        "retrieval_iso_date",
        "repair_nested_math",
        "repair_multiline_if",
        "repair_table_literal",
    }
)


def load_four(cases_path: Path) -> list[dict[str, Any]]:
    with open(cases_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("cases: ожидается JSON-массив")
    out = [c for c in data if str(c.get("id", "")) in TARGET_IDS]
    found = {str(c["id"]) for c in out}
    missing = TARGET_IDS - found
    if missing:
        raise SystemExit(f"Не найдены кейсы: {missing}")
    return sorted(out, key=lambda c: str(c["id"]))


def mini_report(row: dict[str, Any]) -> dict[str, Any]:
    cid = row["id"]
    d = row.get("parsed") or {}
    diag = d.get("diagnostics") if isinstance(d, dict) else None
    http = row.get("http_status")
    err = row.get("error")
    return {
        "id": cid,
        "category": row.get("category"),
        "http_status": http,
        "transport_error": err,
        "latency_s": row.get("latency_s"),
        "response_received": http == 200 and bool(d),
        "status": d.get("status") if d else None,
        "iterations": d.get("iterations") if d else None,
        "used_model": d.get("used_model") if d else None,
        "reflexion_applied": d.get("reflexion_applied") if d else None,
        "first_pass_syntax_ok": d.get("first_pass_syntax_ok") if d else None,
        "syntax_ok": (d.get("validation") or {}).get("syntax_ok") if d else None,
        "diagnostics": diag,
        "message_preview": (d.get("message") or "")[:200] if d else "",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parent / "test_cases.json",
    )
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()
    url = args.base_url.rstrip("/") + "/generate"
    cases = load_four(args.cases)
    rows: list[dict[str, Any]] = []

    print(f"URL={url} timeout={args.timeout}s cases={len(cases)}")
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for c in cases:
            cid = c["id"]
            cat = c.get("category", "")
            t0 = time.perf_counter()
            row: dict[str, Any] = {
                "id": cid,
                "category": cat,
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
                row["error"] = str(e)
                row["latency_s"] = round(time.perf_counter() - t0, 4)
                rows.append(row)
                print(f"[{cid}] TRANSPORT {e}")
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
            print(
                f"[{cid}] http={r.status_code} latency={row['latency_s']}s "
                f"status={p.get('status')} iters={p.get('iterations')} "
                f"model={p.get('used_model')!r} reflexion={p.get('reflexion_applied')}"
            )
            if isinstance(di, dict):
                print(
                    f"       diag: chunks={di.get('retrieval_chunks_count')} "
                    f"gen1_prompt_chars={di.get('gen1_prompt_chars')} "
                    f"review_prompt_chars={di.get('review_prompt_chars')} "
                    f"stage={di.get('stage')!r} failure={di.get('failure_stage')!r}"
                )

    report = {
        "base_url": args.base_url,
        "runs": rows,
        "mini_reports": [mini_report(r) for r in rows],
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
