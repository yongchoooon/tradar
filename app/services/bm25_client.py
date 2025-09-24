"""Naive BM25-like scorer over the in-memory catalogue."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from app.services import catalog
from app.services.embedding_utils import tokenize


class BM25Client:
    def __init__(self) -> None:
        self._documents: Dict[str, Counter[str]] = {}
        for record in catalog.all_trademarks():
            self._documents[record.trademark_id] = Counter(record.text_tokens)

    def search(self, text: str, topn: int = 10) -> List[dict]:
        tokens = tokenize(text)
        if not tokens:
            return []
        query = Counter(tokens)
        scores = []
        for tm_id, doc in self._documents.items():
            overlap = sum(min(query[tok], doc[tok]) for tok in query)
            if overlap == 0:
                continue
            scores.append({"id": tm_id, "score": float(overlap)})
        scores.sort(key=lambda item: item["score"], reverse=True)
        return scores[:topn]
