"""Model registry placeholder."""

from dataclasses import dataclass

from .base import Base


@dataclass
class ModelRegistry(Base):  # type: ignore[misc]
    id: int | None = None
    name: str = ""
    version: str = ""
