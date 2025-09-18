"""Asset model placeholder."""

from dataclasses import dataclass

from .base import Base


@dataclass
class Asset(Base):  # type: ignore[misc]
    id: int | None = None
    trademark_id: int | None = None
    image_url: str | None = None
