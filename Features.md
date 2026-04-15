# Features Added

## 1) Retrieved Chunks in API + UI
- `POST /generate` and `POST /edit` now return `retrieved_chunks`.
- UI displays these chunks in the "Использованная документация" section.

## 2) Explanation Block
- System prompt now requests short explanation after Lua code.
- API responses now include `explanation`.
- UI renders explanation in chat after generation.

## 3) Edit Mode
- Added `POST /edit` endpoint.
- Request format:
  - `instruction`: user request for modifications.
  - `original_code`: Lua source code to edit.
- Edit flow uses same validation and reflexion logic as generation.

## 4) Clarification Router with LLM
- Added first-stage LLM classification prompt: return only `YES` or `NO`.
- If `NO`, API returns `needs_clarification` and generated clarifying question.

## 5) Whoosh-based Documentation Retrieval
- Retriever now supports corpus from:
  - `knowledge/chunks.jsonl`
  - `knowledge/chunks.official.jsonl`
  - legacy `docs_snippets.json`
  - extracted text files from `localscript-openapi.zip` (if present)
- Added BM25 ranking and top-k retrieval.
- Added persistent index directory (`WHOOSH_INDEX_DIR`) for reuse between restarts.
- Added `GET /docs-snippets` for debugging corpus chunks.

## 6) Web Interface
- Added static frontend served by FastAPI from `api/static/`.
- Two-panel layout:
  - Left: chat history + prompt input.
  - Right: code editor with validate/edit actions.
- Validation status panel includes syntax status, model, iterations, retrieved chunks.
- Edit modal sends request to `/edit`.

## 7) New/Updated API Endpoints
- `POST /generate` (extended response).
- `POST /edit` (new).
- `POST /validate` (new).
- `GET /docs-snippets` (new).
- Static frontend at `/` (new).

## 8) Docker Compose Updates
- Added env vars for retriever storage and docs archive paths:
  - `WHOOSH_INDEX_DIR`
  - `DOCS_EXTRACT_DIR`
  - `DOCS_ARCHIVE_PATH`
- Added named volumes:
  - `whoosh_data`
  - `docs_extract_data`
