"""Trademark model placeholder."""

from dataclasses import dataclass

from .base import Base


@dataclass
class Trademark(Base):  # type: ignore[misc]
    id: int | None = None
    title: str = ""
