"""Ingestion related API routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.pipelines.ingest_pipeline import IngestPipeline
from app.schemas.ingest import IngestRequest, IngestResponse

router = APIRouter(prefix="/ingest", tags=["ingest"])
_pipeline = IngestPipeline()


@router.post("/trademark", response_model=IngestResponse)
def ingest_trademark(req: IngestRequest) -> IngestResponse:
    result = _pipeline.ingest(req)
    return IngestResponse(
        application_number=result.application_number,
        task_id=result.task_id,
    )


@router.get("/status/{task_id}")
def ingest_status(task_id: str) -> dict[str, str]:
    return {"task_id": task_id, "status": "completed"}
