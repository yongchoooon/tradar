"""Text embedding service powered by configurable backends."""

from __future__ import annotations

from typing import Iterable, List, Sequence

from app.services.embedding_backends import get_text_backend


class TextEmbedder:
    """Provides helpers to encode single or batched strings."""

    def __init__(self, backend: str | None = None) -> None:
        self._backend = get_text_backend(backend)

    def encode(self, text: str) -> List[float]:
        return self._backend.encode_text(text)

    def encode_batch(self, texts: Sequence[str]) -> List[List[float]]:
        if hasattr(self._backend, "encode_batch"):
            return self._backend.encode_batch(list(texts))
        return [self._backend.encode_text(text) for text in texts]

    def encode_many(self, texts: Sequence[str]) -> List[float]:
        """Pool multiple strings into a single embedding via backend helper."""

        cleaned = [text for text in texts if (text or "").strip()]
        if not cleaned:
            return self.encode("")
        if hasattr(self._backend, "encode_many"):
            return self._backend.encode_many(cleaned)
        # Fallback: average encode_batch outputs
        vectors = self.encode_batch(cleaned)
        dim = len(vectors[0])
        accum = [0.0] * dim
        for vec in vectors:
            if len(vec) != dim:
                raise ValueError("Mismatched embedding dimensions during pooling")
            for idx, value in enumerate(vec):
                accum[idx] += value
        return [value / len(vectors) for value in accum]

    def encode_many_batch(self, groups: Sequence[Sequence[str]]) -> List[List[float]]:
        return [self.encode_many(group) for group in groups]
