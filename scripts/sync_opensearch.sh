#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${DATABASE_URL:?DATABASE_URL must be set (e.g. postgresql://user:pass@host:5432/tradar)}"
: "${OPENSEARCH_URL:?OPENSEARCH_URL must be set (e.g. http://localhost:9200)}"
: "${OPENSEARCH_INDEX:=tradar_trademarks}"
: "${OPENSEARCH_SEARCH_FIELDS:=title_korean^2,title_english,aliases^0.5}"

echo "[sync] exporting trademark metadata from PostgreSQL -> ${OPENSEARCH_URL}/${OPENSEARCH_INDEX}"

python - <<'PY'
import json
import os

from opensearchpy import OpenSearch
import psycopg

database_url = os.environ["DATABASE_URL"]
opensearch_url = os.environ["OPENSEARCH_URL"]
index = os.environ["OPENSEARCH_INDEX"]

client = OpenSearch(opensearch_url)

with psycopg.connect(database_url) as conn, conn.cursor() as cur:
    cur.execute(
        """
        SELECT application_number, title_korean, title_english,
               goods_services, service_classes
        FROM trademarks
        ORDER BY application_number
        """
    )
    rows = cur.fetchall()

bulk_payload = []
for row in rows:
    tm_id, title_ko, title_en, goods, classes = row
    doc = {
        "application_number": tm_id,
        "title_korean": title_ko or "",
        "title_english": title_en or "",
        "goods_services": goods or "",
        "service_classes": classes if isinstance(classes, list) else classes or [],
    }
    bulk_payload.append(json.dumps({"index": {"_index": index, "_id": tm_id}}))
    bulk_payload.append(json.dumps(doc))

BATCH_SIZE = 2000
for start in range(0, len(bulk_payload), BATCH_SIZE):
    chunk = bulk_payload[start:start + BATCH_SIZE]
    client.bulk(body="\n".join(chunk) + "\n")

print(f"[sync] indexed {len(rows)} documents into {index}")
PY

echo "[sync] done"
