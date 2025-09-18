"""Admin schema placeholders."""

try:
    from pydantic import BaseModel
except Exception:
    class BaseModel:  # type: ignore
        pass


class AdminAction(BaseModel):
    """Placeholder admin action."""

    action: str
