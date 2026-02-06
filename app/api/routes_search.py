from fastapi import APIRouter, HTTPException

from app.schemas.search import SearchRequest, SearchResponse
from app.services.worker_bridge import (
    WorkerSearchFailed,
    WorkerSearchTimeout,
    WorkerSearchUnavailable,
    WorkerSearchUploadFailed,
    run_worker_search,
)

router = APIRouter()

@router.post("/search/multimodal", response_model=SearchResponse)
async def search_multimodal(req: SearchRequest) -> SearchResponse:
    try:
        return await run_worker_search(req)
    except WorkerSearchUnavailable as exc:
        raise HTTPException(status_code=503, detail="Desktop worker not connected") from exc
    except WorkerSearchTimeout as exc:
        raise HTTPException(status_code=504, detail="Desktop worker timed out") from exc
    except WorkerSearchUploadFailed as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": getattr(exc, "error_code", "IMAGE_TRANSFER_FAILED"),
                "message": str(exc) or "Failed to prepare image for worker",
            },
        ) from exc
    except WorkerSearchFailed as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "Desktop worker error") from exc
