#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

TARGET_IDS: tuple[str, ...] = (
    "retrieval_iso_date",
    "init_variable",
    "edit_mode_sample",
    "ambiguous_short",
)


def load_cases(cases_path: Path) -> list[dict[str, Any]]:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    by_id = {str(c.get("id")): c for c in data if isinstance(c, dict)}
    out: list[dict[str, Any]] = []
    for cid in TARGET_IDS:
        if cid not in by_id:
            raise SystemExit(f"Case not found: {cid}")
        out.append(by_id[cid])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=float, default=420.0)
    ap.add_argument("--label", default="")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).resolve().parent / "test_cases.json",
    )
    args = ap.parse_args()

    rows: list[dict[str, Any]] = []
    cases = load_cases(args.cases)
    url = args.base_url.rstrip("/") + "/generate"
    with httpx.Client(timeout=args.timeout, trust_env=False) as client:
        for c in cases:
            t0 = time.perf_counter()
            cid = str(c["id"])
            row: dict[str, Any] = {"id": cid}
            try:
                resp = client.post(
                    url,
                    json={
                        "prompt": c["prompt"],
                        "context": c.get("context"),
                        "include_diagnostics": True,
                    },
                )
                row["http_status"] = resp.status_code
                row["latency_s"] = round(time.perf_counter() - t0, 3)
                payload = resp.json() if resp.status_code == 200 else {}
                row["status"] = payload.get("status")
                row["syntax_ok"] = (payload.get("validation") or {}).get("syntax_ok")
                row["gen1_prompt_chars"] = (payload.get("diagnostics") or {}).get(
                    "gen1_prompt_chars"
                )
            except Exception as e:  # noqa: BLE001
                row["http_status"] = None
                row["status"] = "transport_error"
                row["syntax_ok"] = False
                row["latency_s"] = round(time.perf_counter() - t0, 3)
                row["error"] = str(e)
            rows.append(row)

    latencies = [r["latency_s"] for r in rows if isinstance(r.get("latency_s"), (int, float))]
    prompt_chars = [r.get("gen1_prompt_chars") for r in rows if isinstance(r.get("gen1_prompt_chars"), int)]
    summary = {
        "label": args.label,
        "cases_n": len(rows),
        "success_count": sum(1 for r in rows if r.get("status") == "success"),
        "clarification_count": sum(1 for r in rows if r.get("status") == "needs_clarification"),
        "transport_failed": sum(1 for r in rows if r.get("status") == "transport_error"),
        "syntax_ok_count": sum(1 for r in rows if r.get("status") == "success" and r.get("syntax_ok") is True),
        "avg_latency_s": round(statistics.mean(latencies), 3) if latencies else None,
        "avg_gen1_prompt_chars": round(statistics.mean(prompt_chars), 1) if prompt_chars else None,
    }
    report = {"summary": summary, "runs": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

