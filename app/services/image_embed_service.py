"""Image embedding service backed by configurable backends."""

from __future__ import annotations

from typing import Dict, Iterable, List

from app.services.embedding_backends import get_image_backend


class ImageEmbedder:
    """Wrapper that exposes a simple encode API for pipelines/scripts."""

    def __init__(self, backend: str | None = None) -> None:
        self._backend = get_image_backend(backend)

    def encode(self, image_bytes: bytes) -> Dict[str, List[float]]:
        return self._backend.encode(image_bytes)

    def encode_batch(self, images: Iterable[bytes]) -> List[Dict[str, List[float]]]:
        if hasattr(self._backend, "encode_batch"):
            return self._backend.encode_batch(list(images))
        return [self._backend.encode(image) for image in images]
