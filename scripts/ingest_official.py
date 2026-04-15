#!/usr/bin/env python3
"""
Ingestion официальных материалов организаторов → api/knowledge/chunks.official.jsonl

Ожидаемые входы (см. api/knowledge/raw/organizers/README.txt):
  - один или несколько *.pdf  в api/knowledge/raw/organizers/
  - *.zip (например localscript-openapi.zip) с OpenAPI *.yaml / *.yml / *.json

Запуск из корня репозитория:
  pip install -r scripts/requirements-official.txt   # только если есть PDF
  python scripts/ingest_official.py
  python scripts/ingest_official.py --dry-run      # только отчёт, без записи

Поле source в чанках: organizer_pdf | organizer_openapi
Поле kind: constraint | lua_rule | example_task | api_contract | pattern (эвристика)
Поле provenance (опционально): откуда взято (имя файла, страница PDF — если доступна)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parent.parent


def _organizers_dir() -> Path:
    return _root() / "api" / "knowledge" / "raw" / "organizers"


def _out_path() -> Path:
    return _root() / "api" / "knowledge" / "chunks.official.jsonl"


def _guess_kind(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(paths|openapi|swagger)\b", t) and "/" in text[:400]:
        return "api_contract"
    if any(
        x in t
        for x in (
            "огранич",
            "запрет",
            "sandbox",
            "forbidden",
            "security",
            "безопас",
            "не допуска",
        )
    ):
        return "constraint"
    if "пример" in t or "example" in t or "```" in t:
        return "example_task"
    if "lua" in t and ("return" in t or "wf." in t or "script" in t):
        return "lua_rule"
    return "pattern"


def _keywords_from_text(text: str, extra: list[str], cap: int = 14) -> list[str]:
    words = re.findall(r"[\w\u0400-\u04FF]{3,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for w in extra + words:
        w = w.strip()
        if not w or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= cap:
            break
    return out


def _chunk_paragraphs(text: str, max_chars: int = 950) -> list[str]:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        sep = "\n\n" if buf else ""
        if len(buf) + len(sep) + len(p) <= max_chars:
            buf = f"{buf}{sep}{p}" if buf else p
        else:
            if buf:
                chunks.append(buf.strip())
            if len(p) <= max_chars:
                buf = p
            else:
                for i in range(0, len(p), max_chars):
                    part = p[i : i + max_chars].strip()
                    if part:
                        chunks.append(part)
                buf = ""
        if len(buf) > max_chars * 2:
            chunks.append(buf[:max_chars].strip())
            buf = buf[max_chars:].strip()
    if buf.strip():
        chunks.append(buf.strip())
    return [c for c in chunks if len(c) >= 40]


def _extract_pdf(path: Path) -> tuple[str, list[str]]:
    """Возвращает (plain_text, warnings)."""
    warnings: list[str] = []
    try:
        from pypdf import PdfReader  # type: ignore[import-untyped]
    except ImportError:
        warnings.append(
            "pypdf не установлен: pip install -r scripts/requirements-official.txt"
        )
        return "", warnings
    parts: list[str] = []
    try:
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages):
            try:
                t = page.extract_text() or ""
            except Exception as e:  # noqa: BLE001
                warnings.append(f"page {i+1}: {e}")
                t = ""
            if t.strip():
                parts.append(f"\n\n--- PDF {path.name} page {i + 1} ---\n\n{t}")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"PdfReader: {e}")
        return "", warnings
    return "".join(parts), warnings


def _extract_zip_texts(path: Path) -> list[tuple[str, str]]:
    """Список (имя_внутри_zip, текст)."""
    out: list[tuple[str, str]] = []
    with zipfile.ZipFile(path, "r") as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prio = [n for n in names if re.search(r"openapi|swagger", n, re.I)]
        rest = [n for n in names if n not in prio]
        candidates = [
            n
            for n in prio + rest
            if n.lower().endswith((".yaml", ".yml", ".json"))
        ]
        for name in candidates[:40]:
            try:
                data = zf.read(name)
                txt = data.decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            if len(txt) < 20:
                continue
            out.append((name, txt))
    return out


def _build_chunks() -> tuple[list[dict], list[str]]:
    """Чанки + сообщения для stdout."""
    messages: list[str] = []
    org = _organizers_dir()
    if not org.is_dir():
        messages.append(f"MISSING_DIR {org} (создайте каталог organizers)")
        return [], messages

    pdfs = sorted(org.glob("*.pdf"))
    zips = sorted(org.glob("*.zip"))
    if not pdfs and not zips:
        messages.append(
            "MISSING_FILES: нет *.pdf и *.zip в api/knowledge/raw/organizers/ "
            "(см. README.txt там же)"
        )
        return [], messages

    rows: list[dict] = []
    gid = 0

    for pdf in pdfs:
        n_before = len(rows)
        text, warns = _extract_pdf(pdf)
        for w in warns:
            messages.append(f"WARN {pdf.name}: {w}")
        if not text.strip():
            messages.append(f"SKIP_EMPTY_PDF {pdf.name}")
            continue
        for ci, chunk in enumerate(_chunk_paragraphs(text)):
            kind = _guess_kind(chunk)
            gid += 1
            cid = f"official-pdf-{gid:05d}"
            rows.append(
                {
                    "id": cid,
                    "source": "organizer_pdf",
                    "kind": kind,
                    "text": chunk,
                    "keywords": _keywords_from_text(
                        chunk, [pdf.stem, "localscript", "pdf"]
                    ),
                    "provenance": f"pdf:{pdf.name}#chunk{ci}",
                }
            )
        messages.append(f"OK_PDF {pdf.name} chunks={len(rows) - n_before}")

    for zp in zips:
        n_before = len(rows)
        pairs = _extract_zip_texts(zp)
        if not pairs:
            messages.append(f"SKIP_EMPTY_ZIP {zp.name}")
            continue
        for inner, raw in pairs:
            header = f"--- ZIP {zp.name} :: {inner} ---\n\n"
            for ci, chunk in enumerate(_chunk_paragraphs(header + raw)):
                kind = _guess_kind(chunk)
                gid += 1
                cid = f"official-openapi-{gid:05d}"
                rows.append(
                    {
                        "id": cid,
                        "source": "organizer_openapi",
                        "kind": kind,
                        "text": chunk,
                        "keywords": _keywords_from_text(
                            chunk,
                            [zp.stem, "openapi", inner.split("/")[-1][:40]],
                        ),
                        "provenance": f"zip:{zp.name}:{inner}#chunk{ci}",
                    }
                )
        messages.append(f"OK_ZIP {zp.name} chunks={len(rows) - n_before}")

    return rows, messages


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="только отчёт в stdout, без записи chunks.official.jsonl",
    )
    args = ap.parse_args()

    rows, msgs = _build_chunks()
    for m in msgs:
        print(m)

    if not rows:
        print("RESULT: no official chunks written (see messages above)")
        return 0

    kinds = Counter(r["kind"] for r in rows)
    srcs = Counter(r["source"] for r in rows)
    print("STATS kinds:", dict(kinds))
    print("STATS sources:", dict(srcs))
    print(f"TOTAL_CHUNKS {len(rows)}")

    if args.dry_run:
        print("DRY_RUN: not writing file")
        return 0

    out = _out_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
