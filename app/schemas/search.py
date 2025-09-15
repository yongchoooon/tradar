"""Request/response schemas for search endpoints.

The project intends to use Pydantic for data validation as described in the
README, but the execution environment may not have the dependency installed.
To remain compatible we try to import :mod:`pydantic`'s dataclass decorator and
fall back to the standard library's :func:`dataclasses.dataclass` when it isn't
available.  This keeps the public API identical while still enabling optional
validation in environments where Pydantic can be installed.
"""

from typing import List, Optional

try:  # pragma: no cover - tiny shim
    from pydantic.dataclasses import dataclass  # type: ignore
except Exception:  # Pydantic not installed
    from dataclasses import dataclass


@dataclass
class SearchRequest:
    """Parameters accepted by the search pipeline."""

    text: Optional[str] = None
    class_code: Optional[str] = None
    image: Optional[str] = None
    topn: int = 10


@dataclass
class SearchResult:
    """Single search hit with identifier and score."""

    trademark_id: str
    score: float


@dataclass
class SearchResponse:
    """List of search results."""

    results: List[SearchResult]
