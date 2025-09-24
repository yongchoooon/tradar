"""Request/response schemas for multimodal search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

try:  # pragma: no cover
    from pydantic.dataclasses import dataclass as pydantic_dataclass  # type: ignore
except Exception:  # fallback when Pydantic is unavailable
    pydantic_dataclass = dataclass


@pydantic_dataclass
class BoundingBox:
    x1: float
    y1: float
    x2: float
    y2: float


@pydantic_dataclass
class SearchRequest:
    image_b64: str
    boxes: List[BoundingBox] = field(default_factory=list)
    text: Optional[str] = None
    goods_classes: List[str] = field(default_factory=list)
    group_codes: List[str] = field(default_factory=list)
    k: int = 20


@pydantic_dataclass
class SearchResult:
    trademark_id: str
    title: str
    status: str
    class_codes: List[str]
    app_no: str
    image_sim: float
    text_sim: float
    thumb_url: Optional[str] = None


@pydantic_dataclass
class SearchGroups:
    adjacent: List[SearchResult] = field(default_factory=list)
    non_adjacent: List[SearchResult] = field(default_factory=list)
    registered: List[SearchResult] = field(default_factory=list)
    refused: List[SearchResult] = field(default_factory=list)
    others: List[SearchResult] = field(default_factory=list)


@pydantic_dataclass
class QueryInfo:
    k: int
    boxes: int
    text: Optional[str]
    goods_classes: List[str]
    group_codes: List[str]


@pydantic_dataclass
class SearchResponse:
    query: QueryInfo
    image_topk: SearchGroups
    text_topk: SearchGroups
