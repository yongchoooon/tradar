"""FastAPI entrypoint for the backend API (no static assets)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes_goods import router as goods_router
from app.api.routes_media import router as media_router
from app.api.routes_search import router as search_router
from app.api.routes_worker import router as worker_router
from app.api.routes_simulation import router as simulation_router

APP_ENV = os.getenv("APP_ENV")
if not APP_ENV:
    load_dotenv(override=False)
    APP_ENV = os.getenv("APP_ENV", "dev")
APP_ENV = APP_ENV.lower()


def _enforce_environment() -> None:
    required = [
        "DATABASE_URL",
        "OPENSEARCH_URL",
        "OPENAI_API_KEY",
        "KIPRIS_ACCESS_KEY",
    ]
    if APP_ENV == "prod":
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError(
                "Missing required environment variables in prod: " + ", ".join(missing)
            )
    else:
        os.environ.setdefault(
            "DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/tradar"
        )
        os.environ.setdefault("OPENSEARCH_URL", "http://localhost:9200")


_enforce_environment()


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


def _configure_cors(app_: FastAPI) -> None:
    raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins: List[str] = [entry.strip() for entry in raw.split(",") if entry.strip()]
    if APP_ENV != "prod" and not origins:
        origins = ["http://localhost:5173"]
    if APP_ENV == "prod" and not origins:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must be set in prod (e.g. https://your-cloudfront-domain)"
        )
    if origins:
        app_.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )


_configure_cors(app)


@app.get("/health", tags=["infrastructure"])
def health_check():
    """Simple endpoint for ALB/ECS health checks."""
    return {"status": "ok"}

app.include_router(search_router)
app.include_router(worker_router)
app.include_router(goods_router)
app.include_router(media_router)
app.include_router(simulation_router)

custom_frontend_dir = os.getenv("FRONTEND_DIST")
if custom_frontend_dir:
    resolved = Path(custom_frontend_dir).expanduser()
    if resolved.exists():
        app.mount("/", StaticFiles(directory=resolved, html=True), name="frontend")
    else:
        logging.getLogger("simulation").warning(
            "FRONTEND_DIST=%s was provided but does not exist; static serving disabled",
            resolved,
        )
