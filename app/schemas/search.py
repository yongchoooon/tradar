"""Request/response schemas for multimodal search."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

try:  # pragma: no cover
    from pydantic.dataclasses import dataclass as pydantic_dataclass  # type: ignore
except Exception:  # fallback when Pydantic is unavailable
    pydantic_dataclass = dataclass


@pydantic_dataclass
class SearchRequest:
    image_b64: str
    text: Optional[str] = None
    goods_classes: List[str] = field(default_factory=list)
    group_codes: List[str] = field(default_factory=list)
    k: int = 20
    debug: bool = False
    image_prompt: Optional[str] = None
    image_prompt_mode: str = "balanced"
    text_prompt: Optional[str] = None
    text_prompt_mode: str = "balanced"
    variants: Optional[List[str]] = None


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
    doi: Optional[str] = None


@pydantic_dataclass
class DebugRow:
    rank: int
    application_number: str
    score: float


@pydantic_dataclass
class ImageBlendDebugRow:
    rank: int
    application_number: str
    dino: float
    metaclip: float
    blended: float


@pydantic_dataclass
class DebugInfo:
    image_dino: List[DebugRow] = field(default_factory=list)
    image_metaclip: List[DebugRow] = field(default_factory=list)
    text_metaclip: List[DebugRow] = field(default_factory=list)
    text_bm25: List[DebugRow] = field(default_factory=list)
    image_blended: List[ImageBlendDebugRow] = field(default_factory=list)
    text_ranked: List[DebugRow] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)


@pydantic_dataclass
class QueryInfo:
    k: int
    text: Optional[str]
    goods_classes: List[str]
    group_codes: List[str]
    variants: List[str] = field(default_factory=list)


@pydantic_dataclass
class SearchResponse:
    query: QueryInfo
    image_top: List[SearchResult]
    image_misc: List[SearchResult]
    text_top: List[SearchResult]
    text_misc: List[SearchResult]
    debug: Optional[DebugInfo] = None
