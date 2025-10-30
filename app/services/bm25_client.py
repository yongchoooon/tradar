"""OpenSearch-backed BM25 retrieval client."""

from __future__ import annotations

import logging
from typing import List

from app.services import opensearch_client

logger = logging.getLogger(__name__)


class BM25Client:
    def __init__(self) -> None:
        if not opensearch_client.is_configured():
            raise RuntimeError(
                "OPENSEARCH_URL environment variable가 설정되어 있지 않아 BM25 검색을 사용할 수 없습니다."
            )
        try:
            self._client = opensearch_client.get_client()
        except Exception as exc:  # pragma: no cover - depends on cluster state
            raise RuntimeError("OpenSearch 클라이언트 초기화에 실패했습니다.") from exc
        self._index = opensearch_client.get_index_name()
        self._fields = opensearch_client.get_search_fields()
        logger.info(
            "BM25Client OpenSearch index='%s' fields=%s",
            self._index,
            ",".join(self._fields) or "<default>",
        )

    def search(self, text: str, topn: int = 10) -> List[dict]:
        text = (text or "").strip()
        if not text or topn <= 0:
            return []
        try:
            return self._query(text, topn)
        except Exception as exc:  # pragma: no cover - depends on cluster state
            raise RuntimeError("OpenSearch BM25 질의가 실패했습니다.") from exc

    def _query(self, text: str, topn: int) -> List[dict]:
        query = {
            "size": topn,
            "query": {
                "multi_match": {
                    "query": text,
                    "fields": self._fields,
                    "type": "best_fields",
                    "operator": "or",
                    "minimum_should_match": "1",
                }
            },
        }
        response = self._client.search(index=self._index, body=query)
        hits = response.get("hits", {}).get("hits", [])
        results: List[dict] = []
        for hit in hits:
            source = hit.get("_source", {}) or {}
            tm_id = source.get("application_number") or hit.get("_id")
            if not tm_id:
                continue
            score = hit.get("_score", 0.0)
            results.append({"id": tm_id, "score": float(score or 0.0)})
        return results
