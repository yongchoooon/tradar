"""Decision model placeholder."""

from dataclasses import dataclass

from .base import Base


@dataclass
class Decision(Base):  # type: ignore[misc]
    id: int | None = None
    trademark_id: int | None = None
    type: str = ""
    text: str = ""
