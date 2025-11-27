import asyncio
import json
import logging
from dataclasses import asdict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.simulation import (
    SimulationJobCreateResponse,
    SimulationJobStatusResponse,
    SimulationRequest,
)
from app.services.simulation_jobs import job_manager

router = APIRouter()
logger = logging.getLogger("simulation")


@router.post("/simulation/run", response_model=SimulationJobCreateResponse)
def run_simulation_endpoint(
    request: SimulationRequest,
    background_tasks: BackgroundTasks,
) -> SimulationJobCreateResponse:
    if not request.selections:
        raise HTTPException(status_code=400, detail="선택된 상표가 없습니다.")
    logger.info(
        "[/simulation/run] enqueue request with %d selections",
        len(request.selections or []),
    )
    job_id = job_manager.enqueue(request)
    background_tasks.add_task(job_manager.run_job, job_id)
    return SimulationJobCreateResponse(job_id=job_id)


@router.get("/simulation/status/{job_id}", response_model=SimulationJobStatusResponse)
def get_simulation_status(job_id: str) -> SimulationJobStatusResponse:
    record = job_manager.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return SimulationJobStatusResponse(
        job_id=job_id,
        status=record.status,
        result=record.result,
        error=record.error,
    )


@router.get("/simulation/stream/{job_id}")
async def stream_simulation_status(job_id: str):
    async def event_generator():
        last_status = None
        while True:
            record = job_manager.get(job_id)
            if record is None:
                payload = SimulationJobStatusResponse(job_id=job_id, status="not_found")
                yield _format_sse(payload)
                break
            payload = SimulationJobStatusResponse(
                job_id=job_id,
                status=record.status,
                result=record.result,
                error=record.error,
            )
            if record.status != last_status or record.status in {"complete", "failed"}:
                yield _format_sse(payload)
                last_status = record.status
            if record.status in {"complete", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _format_sse(payload: SimulationJobStatusResponse) -> str:
    data = json.dumps(asdict(payload), default=str)
    return f"data: {data}\n\n"
