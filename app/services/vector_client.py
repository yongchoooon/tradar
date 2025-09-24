"""Lightweight vector search client over the in-memory catalogue."""

from __future__ import annotations

from typing import Dict, Iterable, List

from app.services import catalog
from app.services.embedding_utils import cosine


class VectorClient:
    def __init__(self) -> None:
        self._image_vectors: Dict[str, List[float]] = {}
        self._text_vectors: Dict[str, List[float]] = {}
        self._build_cache()

    def _build_cache(self) -> None:
        for record in catalog.all_trademarks():
            self._image_vectors[record.trademark_id] = record.image_embedding
            self._text_vectors[record.trademark_id] = record.text_embedding

    def search(self, kind: str, vec: Iterable[float], topn: int = 10) -> List[dict]:
        cache = self._select_cache(kind)
        if not cache:
            return []
        vec_list = list(vec)
        scores = [
            {"id": tm_id, "score": cosine(vec_list, emb)}
            for tm_id, emb in cache.items()
        ]
        scores.sort(key=lambda item: item["score"], reverse=True)
        return scores[:topn]

    def _select_cache(self, kind: str) -> Dict[str, List[float]]:
        if kind == "image":
            return self._image_vectors
        if kind == "text":
            return self._text_vectors
        raise ValueError(f"Unsupported vector kind: {kind}")
