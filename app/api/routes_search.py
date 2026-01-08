from functools import lru_cache

from fastapi import APIRouter

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter()


@lru_cache(maxsize=1)
def _get_pipeline() -> SearchPipeline:
    return SearchPipeline()

@router.post("/search/multimodal", response_model=SearchResponse)
def search_multimodal(req: SearchRequest) -> SearchResponse:
    return _get_pipeline().search(req)
