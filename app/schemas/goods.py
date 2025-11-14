"""상품/서비스류 검색 응답 스키마."""

from __future__ import annotations

from dataclasses import  field
from typing import List

try:  # pragma: no cover - 선택 의존성
    from pydantic.dataclasses import dataclass as pydantic_dataclass  # type: ignore
except Exception:
    from dataclasses import dataclass as pydantic_dataclass


@pydantic_dataclass
class GoodsGroupItem:
    similar_group_code: str
    names: List[str]
    score: float


@pydantic_dataclass
class GoodsClassItem:
    nc_class: str
    class_name: str
    score: float
    groups: List[GoodsGroupItem] = field(default_factory=list)


@pydantic_dataclass
class GoodsSearchResponse:
    query: str
    results: List[GoodsClassItem]
