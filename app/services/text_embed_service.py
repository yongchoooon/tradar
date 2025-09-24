"""Deterministic toy text embedder."""

from __future__ import annotations

from typing import List

from app.services.embedding_utils import hashed_embedding, tokenize


class TextEmbedder:
    def encode(self, text: str) -> List[float]:
        tokens = tokenize(text) or ["blank"]
        return hashed_embedding(tokens)
