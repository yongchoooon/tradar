"""Embedding model placeholder."""

from dataclasses import dataclass

from .base import Base


@dataclass
class Embedding(Base):  # type: ignore[misc]
    id: int | None = None
    trademark_id: int | None = None
    type: str = "text"
    vec: list[float] | None = None
