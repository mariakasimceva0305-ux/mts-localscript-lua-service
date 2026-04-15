Knowledge layer
=================

Файлы корпуса (порядок загрузки в retriever):
1) knowledge/chunks.jsonl       — manual / examples / tests_summary
2) knowledge/chunks.official.jsonl — после `scripts/ingest_official.py` (PDF + OpenAPI из zip)
3) docs_snippets.json             — legacy baseline

Официальные материалы:
- Положите PDF и/или zip в knowledge/raw/organizers/ (см. README в той папке).
- Установите pypdf для PDF: pip install -r scripts/requirements-official.txt
- Запуск: python scripts/ingest_official.py
- Проверка всего корпуса: python scripts/ingest_knowledge.py

Поля jsonl:
- id, source, kind, text, keywords[] — обязательны для retrieval
- provenance — опционально (для официальных чанков: файл, страница, путь в zip)
