import asyncio
import json
import logging
from dataclasses import asdict, replace

import os

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas.simulation import (
    SimulationJobCreateResponse,
    SimulationJobStatusResponse,
    SimulationRequest,
    SimulationConfigResponse,
)
from app.services.simulation_jobs import job_manager
from app.services.search_cache import search_cache
from app.services.request_meta import get_request_meta

router = APIRouter()
logger = logging.getLogger("simulation")


@router.post("/simulation/run", response_model=SimulationJobCreateResponse)
def run_simulation_endpoint(
    request: SimulationRequest,
    background_tasks: BackgroundTasks,
) -> SimulationJobCreateResponse:
    meta = get_request_meta()
    if meta:
        request = replace(
            request,
            client_id=meta.client_id,
            client_ip=meta.client_ip,
            user_agent=meta.user_agent,
            request_id=meta.request_id,
        )
    if not request.search_id and not request.selections:
        raise HTTPException(status_code=400, detail="검색 컨텍스트가 없습니다. 다시 검색해 주세요.")
    if not request.selection_refs and not request.selections:
        raise HTTPException(status_code=400, detail="선택된 상표가 없습니다.")

    cache_entry = search_cache.get(request.search_id) if request.search_id else None
    inline_map = {
        (sel.application_number, sel.variant): sel
        for sel in (request.selections or [])
        if sel.application_number
    }
    selections = []
    missing = 0
    if cache_entry:
        for ref in request.selection_refs or []:
            key = (ref.application_number, ref.variant)
            selection = cache_entry.selections.get(key) or inline_map.get(key)
            if selection is None:
                missing += 1
                continue
            selections.append(selection)
    else:
        if request.selection_refs:
            for ref in request.selection_refs:
                key = (ref.application_number, ref.variant)
                selection = inline_map.get(key)
                if selection is None:
                    missing += 1
                    continue
                selections.append(selection)
        else:
            selections = list(inline_map.values())
        if selections:
            logger.info(
                "[/simulation/run] search context missing; using inline selections search_id=%s selections=%d",
                request.search_id,
                len(selections),
            )

    if not selections:
        if not cache_entry:
            raise HTTPException(status_code=400, detail="검색 컨텍스트가 만료되었습니다. 다시 검색해 주세요.")
        raise HTTPException(status_code=400, detail="선택된 상표를 찾을 수 없습니다.")
    if missing:
        logger.warning(
            "[/simulation/run] missing selections=%d search_id=%s",
            missing,
            request.search_id,
        )
    request = replace(request, selections=selections)
    try:
        payload_bytes = len(json.dumps(asdict(request), default=str).encode("utf-8"))
    except Exception:
        payload_bytes = -1
    logger.info(
        "[/simulation/run] enqueue selections=%d refs=%d search_id=%s goods_names=%d image_ref=%s payload_bytes=%s",
        len(request.selections or []),
        len(request.selection_refs or []),
        request.search_id,
        len(request.user_goods_names or []),
        bool(request.user_image_ref),
        payload_bytes,
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
            if record.status != last_status or record.status in {"complete", "failed", "cancelled"}:
                yield _format_sse(payload)
                last_status = record.status
            if record.status in {"complete", "failed", "cancelled"}:
                break
            await asyncio.sleep(1)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=headers,
    )


def _format_sse(payload: SimulationJobStatusResponse) -> str:
    data = json.dumps(asdict(payload), default=str)
    return f"data: {data}\n\n"


@router.get("/simulation/config", response_model=SimulationConfigResponse)
def get_simulation_config() -> SimulationConfigResponse:
    model_name = os.getenv("SIMULATION_LLM_MODEL", "gpt-5-nano")
    return SimulationConfigResponse(model_name=model_name)


@router.post("/simulation/cancel/{job_id}", response_model=SimulationJobStatusResponse)
def cancel_simulation(job_id: str) -> SimulationJobStatusResponse:
    record = job_manager.cancel(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="작업을 찾을 수 없습니다.")
    return SimulationJobStatusResponse(
        job_id=job_id,
        status=record.status,
        result=record.result,
        error=record.error,
    )
