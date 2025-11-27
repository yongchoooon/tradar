from pathlib import Path
import logging

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes_goods import router as goods_router
from app.api.routes_media import router as media_router
from app.api.routes_search import router as search_router
from app.api.routes_simulation import router as simulation_router

load_dotenv()


def _configure_logging() -> None:
    logger = logging.getLogger("simulation")
    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] [%(name)s] %(levelname)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


_configure_logging()

app = FastAPI(title="Trademark Search Service")
app.include_router(search_router)
app.include_router(goods_router)
app.include_router(media_router)
app.include_router(simulation_router)

BASE_DIR = Path(__file__).resolve().parent
app.mount(
    "/",
    StaticFiles(directory=BASE_DIR / "frontend", html=True),
    name="frontend",
)
