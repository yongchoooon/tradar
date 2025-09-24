from fastapi import APIRouter

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import SearchRequest, SearchResponse

router = APIRouter()
_pipeline = SearchPipeline()

@router.post("/search/multimodal", response_model=SearchResponse)
def search_multimodal(req: SearchRequest) -> SearchResponse:
    return _pipeline.search(req)
