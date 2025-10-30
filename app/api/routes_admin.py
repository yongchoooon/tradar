"""Administrative API routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.schemas.admin import AdminMessage, ModelRegistration

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/models/register", response_model=AdminMessage)
def register_model(req: ModelRegistration) -> AdminMessage:
    detail = f"registered {req.name}:{req.version} for task {req.task}"
    return AdminMessage(detail=detail)


@router.post("/reindex", response_model=AdminMessage)
def trigger_reindex(application_number: str) -> AdminMessage:
    return AdminMessage(detail=f"reindex scheduled for {application_number}")
