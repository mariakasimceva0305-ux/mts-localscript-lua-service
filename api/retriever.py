"""Whoosh retriever with persistent index and ZIP ingestion."""

from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_API_DIR = Path(__file__).resolve().parent
_SNIPPETS_PATH = _API_DIR / "docs_snippets.json"
_JSONL_PATH = _API_DIR / "knowledge" / "chunks.jsonl"
_OFFICIAL_JSONL_PATH = _API_DIR / "knowledge" / "chunks.official.jsonl"
_KNOWLEDGE_DIR = _API_DIR / "knowledge"
_DOCS_ZIP_PATH = Path(
    os.environ.get(
        "DOCS_ARCHIVE_PATH",
        str(_KNOWLEDGE_DIR / "raw" / "organizers" / "localscript-openapi.zip"),
    )
)
_EXTRACT_DIR = Path(
    os.environ.get("DOCS_EXTRACT_DIR", str(_KNOWLEDGE_DIR / "extracted_docs"))
)
_INDEX_DIR = Path(
    os.environ.get("WHOOSH_INDEX_DIR", str(_API_DIR / "data" / "whoosh_index"))
)

_chunks_cache: list["KnowledgeChunk"] | None = None
_whoosh_warned_missing = False


@dataclass(frozen=True)
class KnowledgeChunk:
    id: str
    source: str
    kind: str
    text: str
    keywords: tuple[str, ...]

    def index_body(self) -> str:
        kw = " ".join(self.keywords)
        return f"{kw} {kw} {self.text}"


def _tokenize_query(blob: str) -> list[str]:
    """Токены для OR-запроса Whoosh (кириллица + латиница, минимум 2 символа)."""
    t = blob.lower()
    found = re.findall(r"[\w\u0400-\u04FF]{2,}", t)
    stop = frozenset(
        {"or", "and", "not", "the", "a", "an", "is", "it", "to", "of", "in", "on"}
    )
    out: list[str] = []
    seen: set[str] = set()
    for w in found:
        if w in stop:
            continue
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= 48:
            break
    return out


def _load_jsonl_chunks(path: Path) -> list[KnowledgeChunk]:
    if not path.is_file():
        return []
    rows: list[KnowledgeChunk] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning("knowledge jsonl %s:%s skip: %s", path, lineno, e)
                continue
            try:
                cid = str(row["id"]).strip()
                src = str(row.get("source", "corpus")).strip() or "corpus"
                kind = str(row.get("kind", "snippet")).strip() or "snippet"
                text = str(row["text"]).strip()
                kws = row.get("keywords", [])
                if not cid or not text:
                    continue
                kw_t = tuple(str(k).strip() for k in kws if str(k).strip())
            except (KeyError, TypeError, ValueError):
                logger.warning("knowledge jsonl %s:%s invalid shape", path, lineno)
                continue
            rows.append(
                KnowledgeChunk(
                    id=cid, source=src, kind=kind, text=text, keywords=kw_t
                )
            )
    return rows


def _load_legacy_snippets(path: Path) -> list[KnowledgeChunk]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    out: list[KnowledgeChunk] = []
    for i, item in enumerate(data):
        kws = item.get("keywords", [])
        kw_t = tuple(str(k).strip() for k in kws if str(k).strip())
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        out.append(
            KnowledgeChunk(
                id=f"snippet-{i}",
                source="docs_snippets.json",
                kind="snippet",
                text=text,
                keywords=kw_t,
            )
        )
    return out


def _iter_all_chunks() -> Iterator[KnowledgeChunk]:
    yield from _load_jsonl_chunks(_JSONL_PATH)
    yield from _load_jsonl_chunks(_OFFICIAL_JSONL_PATH)
    yield from _load_legacy_snippets(_SNIPPETS_PATH)
    yield from _load_zip_chunks()


def _load_corpus() -> list[KnowledgeChunk]:
    global _chunks_cache
    if _chunks_cache is None:
        merged: list[KnowledgeChunk] = list(_iter_all_chunks())
        if not merged:
            logger.warning("Knowledge corpus пуст: нет %s и %s", _JSONL_PATH, _SNIPPETS_PATH)
        _chunks_cache = merged
        n_snip = sum(1 for c in merged if c.source == "docs_snippets.json")
        n_zip = sum(1 for c in merged if c.source == "localscript-openapi.zip")
        n_manual = len(merged) - n_snip - n_zip
        logger.info(
            "Knowledge corpus loaded: total=%s (manual_jsonl=%s, zip=%s, snippets=%s)",
            len(merged),
            n_manual,
            n_zip,
            n_snip,
        )
    return _chunks_cache


def _keyword_hits(chunk: KnowledgeChunk, blob_l: str) -> int:
    return sum(1 for k in chunk.keywords if k.lower() in blob_l)


def _keyword_score(chunk: KnowledgeChunk, blob_l: str) -> float:
    """Доп. вес за совпадение ключевых слов (как в baseline)."""
    n = _keyword_hits(chunk, blob_l)
    return 2.5 * n if n else 0.0


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="ignore")
    except Exception:
        return ""


def _chunk_text(text: str, *, max_chars: int = 1200) -> list[str]:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return []
    chunks: list[str] = []
    for i in range(0, len(clean), max_chars):
        part = clean[i : i + max_chars].strip()
        if len(part) >= 100:
            chunks.append(part)
    return chunks[:25]


def _extract_zip_if_needed() -> None:
    if not _DOCS_ZIP_PATH.is_file():
        logger.warning("Docs ZIP not found at %s", _DOCS_ZIP_PATH)
        return
    _EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    marker = _EXTRACT_DIR / ".zip_extracted"
    zip_mtime = int(_DOCS_ZIP_PATH.stat().st_mtime)
    if marker.is_file():
        try:
            cached_mtime = int(marker.read_text(encoding="utf-8").strip())
            if cached_mtime == zip_mtime:
                return
        except Exception:
            pass
    with zipfile.ZipFile(_DOCS_ZIP_PATH, "r") as archive:
        archive.extractall(_EXTRACT_DIR)
    marker.write_text(str(zip_mtime), encoding="utf-8")
    logger.info("Extracted docs archive: %s -> %s", _DOCS_ZIP_PATH, _EXTRACT_DIR)


def _load_zip_chunks() -> Iterator[KnowledgeChunk]:
    _extract_zip_if_needed()
    if not _EXTRACT_DIR.exists():
        return
    file_idx = 0
    for path in _EXTRACT_DIR.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".yaml", ".yml", ".txt", ".md"}:
            continue
        text = _read_text_file(path)
        for part_idx, part in enumerate(_chunk_text(text), 1):
            file_idx += 1
            rel = path.relative_to(_EXTRACT_DIR).as_posix()
            terms = _tokenize_query(f"{rel} {part[:200]}")
            yield KnowledgeChunk(
                id=f"zip-{file_idx}-{part_idx}",
                source="localscript-openapi.zip",
                kind=rel,
                text=part,
                keywords=tuple(terms[:10]),
            )


def _build_index(chunks: list[KnowledgeChunk]) -> Any:
    global _whoosh_warned_missing
    try:
        from whoosh.fields import ID, KEYWORD, Schema, TEXT
        from whoosh.index import create_in, exists_in, open_dir
    except ModuleNotFoundError:
        if not _whoosh_warned_missing:
            logger.warning(
                "Whoosh не установлен; retrieval работает в keyword-only режиме. "
                "Для BM25 установите dependency whoosh."
            )
            _whoosh_warned_missing = True
        return None

    schema = Schema(
        chunk_id=ID(stored=True, unique=True),
        source=ID(stored=True),
        kind=ID(stored=True),
        text=TEXT(stored=True),
        keywords=KEYWORD(stored=True, commas=True, lowercase=True),
        body=TEXT(stored=True),
    )

    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    if exists_in(_INDEX_DIR):
        ix = open_dir(_INDEX_DIR)
        with ix.searcher() as searcher:
            if searcher.doc_count() > 0:
                return ix
    ix = create_in(_INDEX_DIR, schema, indexname="knowledge")
    writer = ix.writer()
    for ch in chunks:
        writer.add_document(
            chunk_id=ch.id,
            source=ch.source,
            kind=ch.kind,
            text=ch.text,
            keywords=",".join(ch.keywords),
            body=ch.index_body(),
        )
    writer.commit(optimize=True)
    logger.info("Built Whoosh index with %s chunks in %s", len(chunks), _INDEX_DIR)
    return ix


def _bm25_scores(
    ix: Any,
    chunks_by_id: dict[str, dict[str, Any]],
    terms: list[str],
) -> dict[str, tuple[float, dict[str, Any]]]:
    if ix is None:
        return {}
    from whoosh import scoring
    from whoosh.qparser import OrGroup, QueryParser

    scores: dict[str, tuple[float, dict[str, Any]]] = {}
    if not terms:
        return scores
    qstr = " OR ".join(terms)
    try:
        with ix.searcher(weighting=scoring.BM25F()) as searcher:
            qp = QueryParser("body", ix.schema, group=OrGroup)
            q = qp.parse(qstr)
            results = searcher.search(q, limit=120)
            for hit in results:
                cid = hit["chunk_id"]
                if cid in chunks_by_id:
                    meta = {
                        "source": hit.get("source", ""),
                        "kind": hit.get("kind", ""),
                        "text": hit.get("text", ""),
                        "keywords": tuple((hit.get("keywords", "") or "").split(",")),
                    }
                    prev_score = scores.get(cid, (0.0, {}))[0]
                    score = max(prev_score, float(hit.score or 0.0))
                    scores[cid] = (score, meta)
    except Exception as e:
        logger.warning("Whoosh search failed, keyword-only fallback: %s", e)
    return scores


def retrieve_for_generation(
    user_prompt: str,
    extra_text: str = "",
    *,
    log: bool = True,
) -> dict[str, Any]:
    """
    Возвращает:
      formatted — текст для SYSTEM_GENERATION_TEMPLATE;
      chunks — список выбранных чанков с score и метаданными;
      query_terms — токены запроса (для отладки).
    """
    top_k = int(os.environ.get("RETRIEVAL_TOP_K", "4"))
    top_k = max(1, min(top_k, 24))
    max_chunk_chars = int(os.environ.get("RETRIEVAL_CHUNK_MAX_CHARS", "340"))
    max_chunk_chars = max(180, min(max_chunk_chars, 900))
    max_total_chars = int(os.environ.get("RETRIEVAL_TOTAL_MAX_CHARS", "1200"))
    max_total_chars = max(500, min(max_total_chars, 3000))

    blob = f"{user_prompt}\n{extra_text}".strip()
    blob_l = blob.lower()
    terms = _tokenize_query(blob)

    chunks = _load_corpus()
    by_id = {
        c.id: {"source": c.source, "kind": c.kind, "text": c.text, "keywords": c.keywords}
        for c in chunks
    }

    bm25: dict[str, tuple[float, dict[str, Any]]] = {}
    if chunks and terms:
        ix = _build_index(chunks)
        if ix is not None:
            bm25 = _bm25_scores(ix, by_id, terms)

    combined: list[dict[str, Any]] = []
    for cid, meta in by_id.items():
        base = bm25.get(cid, (0.0, {}))[0]
        ch = KnowledgeChunk(
            id=cid,
            source=str(meta.get("source", "")),
            kind=str(meta.get("kind", "")),
            text=str(meta.get("text", "")),
            keywords=tuple(meta.get("keywords", ()) or ()),
        )
        kw = _keyword_score(ch, blob_l)
        combined.append({"id": cid, "meta": meta, "score": base + kw, "keyword_hits": _keyword_hits(ch, blob_l)})

    combined.sort(key=lambda x: x["score"], reverse=True)
    positive = [row for row in combined if row["score"] > 0]
    if positive:
        picked = positive[:top_k]
    else:
        picked = combined[:top_k]

    # Дедупликация очень похожих чанков: меньше шума в prompt, ниже latency.
    deduped: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    for row in picked:
        text = str(row["meta"].get("text", ""))
        sig = re.sub(r"\s+", " ", text).strip().lower()[:180]
        if sig and sig in seen_signatures:
            continue
        if sig:
            seen_signatures.add(sig)
        deduped.append(row)
        if len(deduped) >= top_k:
            break

    budgeted: list[dict[str, Any]] = []
    budget_used = 0
    for row in deduped:
        text = str(row["meta"].get("text", ""))
        cut = text if len(text) <= max_chunk_chars else text[: max_chunk_chars - 1].rstrip() + "…"
        add_len = len(cut)
        if budgeted and budget_used + add_len > max_total_chars:
            continue
        budgeted.append(row)
        budget_used += add_len
        if len(budgeted) >= top_k:
            break
    if not budgeted and deduped:
        budgeted = [deduped[0]]

    chunk_rows: list[dict[str, Any]] = []
    for rank, row in enumerate(budgeted, 1):
        text = str(row["meta"].get("text", ""))
        text_for_prompt = text if len(text) <= max_chunk_chars else text[: max_chunk_chars - 1].rstrip() + "…"
        chunk_rows.append(
            {
                "rank": rank,
                "id": row["id"],
                "source": row["meta"].get("source", ""),
                "kind": row["meta"].get("kind", ""),
                "score": round(float(row["score"]), 5),
                "keyword_hits": row["keyword_hits"],
                "text": text_for_prompt,
                "text_preview": text if len(text) <= 320 else text[:317] + "…",
            }
        )

    if not budgeted:
        formatted = "(релевантных фрагментов не найдено — следуй общим правилам платформы)"
    else:
        lines = []
        for row in budgeted:
            meta = row["meta"]
            src = meta.get("source")
            kind = meta.get("kind")
            text = str(meta.get("text", ""))
            compact_text = text if len(text) <= max_chunk_chars else text[: max_chunk_chars - 1].rstrip() + "…"
            lines.append(f"- [{src}/{kind}] {compact_text}")
        formatted = "\n".join(lines)

    if log:
        logger.info(
            "Retrieval top-%s: %s",
            top_k,
            json.dumps(
                [
                    {"id": r["id"], "score": r["score"], "kw": r["keyword_hits"]}
                    for r in chunk_rows
                ],
                ensure_ascii=False,
            ),
        )

    return {
        "formatted": formatted,
        "chunks": chunk_rows,
        "query_terms": terms,
        "corpus_size": len(chunks),
    }


def retrieve_for_prompt(user_prompt: str, extra_text: str = "") -> str:
    """Обратная совместимость: только текст для промпта."""
    return retrieve_for_generation(user_prompt, extra_text, log=True)["formatted"]


def list_docs_snippets() -> list[dict[str, Any]]:
    rows = []
    for idx, chunk in enumerate(_load_corpus(), 1):
        rows.append(
            {
                "rank": idx,
                "id": chunk.id,
                "source": chunk.source,
                "kind": chunk.kind,
                "score": 0.0,
                "keyword_hits": 0,
                "text": chunk.text,
                "text_preview": chunk.text if len(chunk.text) <= 320 else chunk.text[:317] + "…",
            }
        )
    rows.sort(key=lambda x: (x.get("source", ""), x.get("kind", ""), x.get("id", "")))
    return rows
