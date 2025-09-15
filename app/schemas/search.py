from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SearchRequest:
    text: Optional[str] = None
    topn: int = 10


@dataclass
class SearchResult:
    trademark_id: str
    score: float


@dataclass
class SearchResponse:
    results: List[SearchResult]
