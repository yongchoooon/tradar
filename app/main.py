from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_goods import router as goods_router
from app.api.routes_media import router as media_router
from app.api.routes_search import router as search_router

app = FastAPI(title="Trademark Search Service")
app.include_router(search_router)
app.include_router(goods_router)
app.include_router(media_router)

BASE_DIR = Path(__file__).resolve().parent
app.mount(
    "/",
    StaticFiles(directory=BASE_DIR / "frontend", html=True),
    name="frontend",
)
