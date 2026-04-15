Ожидаемые официальные материалы (положите файлы сюда, затем запустите scripts/ingest_official.py)
================================================================================

Рекомендуемые имена (или любые *.pdf / один zip с OpenAPI):

1) LocalScript Public PDF
   - Пример имени: LocalScript-public.pdf
   - Любой другой *.pdf в этой папке тоже будет обработан.

2) OpenAPI архив
   - Пример имени: localscript-openapi.zip
   - Любой другой *.zip: внутри ищутся файлы *.yaml, *.yml, *.json (приоритет по имени *openapi*).

Результат ingestion (не коммитьте в секретный репозиторий при необходимости):
  api/knowledge/chunks.official.jsonl

Зависимости для PDF (на машине разработчика / CI, не обязательны в Docker api):
  pip install -r scripts/requirements-official.txt

YAML внутри zip читается как текст (без pyyaml), достаточно для lexical/BM25 retrieval.
