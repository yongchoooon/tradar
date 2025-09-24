from fastapi import APIRouter, Query

from app.schemas.goods import GoodsSearchResponse
from app.services.goods_search import search_goods

router = APIRouter()


@router.get("/goods/search", response_model=GoodsSearchResponse)
def goods_search(q: str = Query(..., min_length=1, description="검색어")) -> GoodsSearchResponse:
    return search_goods(q)
