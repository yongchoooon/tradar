from fastapi import FastAPI

from app.api.routes_search import router as search_router

app = FastAPI(title="Trademark Search Service")
app.include_router(search_router)


