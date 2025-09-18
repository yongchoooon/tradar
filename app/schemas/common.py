"""Common Pydantic schema placeholders."""

try:  # pragma: no cover
    from pydantic import BaseModel
except Exception:  # Pydantic not available
    class BaseModel:  # type: ignore
        pass


class Message(BaseModel):
    """Simple message response."""

    detail: str
