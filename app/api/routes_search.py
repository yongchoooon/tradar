from fastapi import APIRouter

from app.schemas.search import SearchRequest, SearchResponse
from app.pipelines.search_pipeline import SearchPipeline

router = APIRouter()

_pipeline = SearchPipeline()

@router.post("/search/trademark", response_model=SearchResponse)
def search_trademark(req: SearchRequest) -> SearchResponse:
    return _pipeline.search(req)
