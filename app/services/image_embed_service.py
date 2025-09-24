"""Deterministic toy image embedder."""

from __future__ import annotations

from typing import List

from app.services.embedding_utils import hashed_embedding, tokenize


class ImageEmbedder:
    def encode(self, image: bytes) -> List[float]:
        text = image.decode("utf-8", errors="ignore")
        tokens = tokenize(text) or ["blank"]
        return hashed_embedding(tokens)
