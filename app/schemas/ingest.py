"""Ingest related schema placeholders."""

from typing import Optional

try:
    from pydantic import BaseModel
except Exception:
    class BaseModel:  # type: ignore
        pass


class IngestRequest(BaseModel):
    """Placeholder request for ingestion."""

    source: Optional[str] = None
