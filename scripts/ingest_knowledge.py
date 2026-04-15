#!/usr/bin/env python3
"""
Проверка knowledge-корпуса: chunks.jsonl + chunks.official.jsonl + docs_snippets.json.

Запуск из корня репозитория:
  python scripts/ingest_knowledge.py
  python scripts/ingest_knowledge.py --print-merged   # id + source + kind всех чанков
  python scripts/ingest_knowledge.py --by-source    # сводка по полю source
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    if not path.is_file():
        return rows
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise SystemExit(f"{path}:{i}: JSON error: {e}") from e
    return rows


def load_snippets(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_chunk(row: dict, loc: str) -> None:
    for k in ("id", "source", "kind", "text", "keywords"):
        if k not in row:
            raise SystemExit(f"{loc}: missing key {k!r}")
    if not isinstance(row["keywords"], list):
        raise SystemExit(f"{loc}: keywords must be list")
    if not row["id"]:
        raise SystemExit(f"{loc}: empty id")
    prov = row.get("provenance")
    if prov is not None and not isinstance(prov, str):
        raise SystemExit(f"{loc}: provenance must be str or omitted")


def source_bucket(src: str) -> str:
    if src in ("organizer_pdf", "organizer_openapi"):
        return "official_materials"
    if src == "tests_summary":
        return "examples_tests"
    if src == "manual":
        return "manual_snippets"
    return "other_manual_jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print-merged", action="store_true")
    ap.add_argument(
        "--by-source",
        action="store_true",
        help="сводка по полю source и агрегированным категориям",
    )
    args = ap.parse_args()
    root = _root()
    api = root / "api"
    manual = api / "knowledge" / "chunks.jsonl"
    official = api / "knowledge" / "chunks.official.jsonl"
    snip_path = api / "docs_snippets.json"

    manual_rows = load_jsonl(manual)
    for i, row in enumerate(manual_rows):
        validate_chunk(row, f"chunks.jsonl#{i+1}")

    official_rows = load_jsonl(official)
    for i, row in enumerate(official_rows):
        validate_chunk(row, f"chunks.official.jsonl#{i+1}")

    snippets = load_snippets(snip_path)

    seen: set[str] = set()
    for row in manual_rows + official_rows:
        rid = row["id"]
        if rid in seen:
            raise SystemExit(f"duplicate chunk id across jsonl: {rid!r}")
        seen.add(rid)

    print(f"OK: chunks.jsonl records={len(manual_rows)}")
    print(f"OK: chunks.official.jsonl records={len(official_rows)}")
    print(f"OK: docs_snippets.json items={len(snippets)}")

    if args.by_source or args.print_merged:
        ctr = Counter(str(r.get("source", "")) for r in manual_rows + official_rows)
        print("BY_SOURCE:", dict(sorted(ctr.items())))
        buckets = Counter(
            source_bucket(str(r.get("source", ""))) for r in manual_rows + official_rows
        )
        print("BY_BUCKET:", dict(sorted(buckets.items())))

    if args.print_merged:
        for row in manual_rows:
            print(row["id"], row["source"], row["kind"], sep="\t")
        for row in official_rows:
            print(row["id"], row["source"], row["kind"], sep="\t")
        for i, _ in enumerate(snippets):
            print(f"snippet-{i}", "docs_snippets", "snippet", sep="\t")

    if not official_rows:
        print(
            "HINT: нет chunks.official.jsonl — положите PDF/zip в "
            "api/knowledge/raw/organizers/ и выполните: python scripts/ingest_official.py"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
