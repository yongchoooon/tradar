"""Dispatch search jobs to the desktop worker and map results."""

from __future__ import annotations

import base64
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.schemas.search import (
    DebugInfo,
    DebugRow,
    ImageBlendDebugRow,
    QueryInfo,
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from app.services.s3_storage import ImageRef, ImageTransferError, build_image_ref
from app.services.worker_registry import (
    WorkerDisconnectedError,
    WorkerTimeoutError,
    WorkerUnavailableError,
    worker_registry,
)
from app.services.search_cache import search_cache
from app.services.worker_settings import get_worker_settings


logger = logging.getLogger(__name__)


class WorkerSearchError(Exception):
    """Base search error when using desktop worker."""


class WorkerSearchUnavailable(WorkerSearchError):
    """No worker connected."""


class WorkerSearchTimeout(WorkerSearchError):
    """Worker did not respond in time."""


class WorkerSearchFailed(WorkerSearchError):
    """Worker returned an error result."""


class WorkerSearchUploadFailed(WorkerSearchError):
    """Failed to upload image or build image reference."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _decode_image_b64(payload: str | None) -> bytes:
    if not payload:
        raise ValueError("image_b64 is required")
    if payload.startswith("data:"):
        _, _, encoded = payload.partition(",")
        payload = encoded
    return base64.b64decode(payload)


def _build_job_payload(req: SearchRequest, image_ref: ImageRef, job_id: str, top_k: int) -> Dict[str, Any]:
    request_meta = {
        "text": req.text,
        "language": req.language,
        "goods_classes": list(req.goods_classes or []),
        "group_codes": list(req.group_codes or []),
        "variants": req.variants,
        "use_llm_variants": req.use_llm_variants,
        "debug": bool(req.debug),
    }
    payload = {
        "type": "job",
        "job_id": job_id,
        "task": "image_search",
        "image_ref": image_ref.as_payload(),
        "top_k": top_k,
        "request_meta": request_meta,
    }
    return payload


def _candidate_to_result(candidate: Dict[str, Any]) -> SearchResult:
    extra_meta = candidate.get("extra_meta") or {}
    return SearchResult(
        trademark_id=str(candidate.get("doc_id") or ""),
        title=str(candidate.get("title") or ""),
        status=str(candidate.get("status") or ""),
        class_codes=list(candidate.get("nc_codes") or []),
        app_no=str(extra_meta.get("app_no") or candidate.get("doc_id") or ""),
        image_sim=float(candidate.get("score_image") or 0.0),
        text_sim=float(candidate.get("score_text") or 0.0),
        thumb_url=candidate.get("thumbnail_ref"),
        doi=extra_meta.get("doi"),
        image_path=extra_meta.get("image_path"),
        goods_services=extra_meta.get("goods_services"),
    )


def _rows_from_payload(rows: Optional[List[Dict[str, Any]]]) -> List[DebugRow]:
    if not rows:
        return []
    payload: List[DebugRow] = []
    for row in rows:
        try:
            payload.append(
                DebugRow(
                    rank=int(row.get("rank") or 0),
                    application_number=str(row.get("application_number") or ""),
                    score=float(row.get("score") or 0.0),
                )
            )
        except Exception:
            continue
    return payload


def _image_rows_from_payload(rows: Optional[List[Dict[str, Any]]]) -> List[ImageBlendDebugRow]:
    if not rows:
        return []
    payload: List[ImageBlendDebugRow] = []
    for row in rows:
        try:
            payload.append(
                ImageBlendDebugRow(
                    rank=int(row.get("rank") or 0),
                    application_number=str(row.get("application_number") or ""),
                    dino=float(row.get("dino") or 0.0),
                    metaclip=float(row.get("metaclip") or 0.0),
                    blended=float(row.get("blended") or 0.0),
                )
            )
        except Exception:
            continue
    return payload


def _debug_from_payload(payload: Optional[Dict[str, Any]]) -> Optional[DebugInfo]:
    if not payload:
        return None
    return DebugInfo(
        image_dino=_rows_from_payload(payload.get("image_dino")),
        image_metaclip=_rows_from_payload(payload.get("image_metaclip")),
        text_metaclip=_rows_from_payload(payload.get("text_metaclip")),
        text_bm25=_rows_from_payload(payload.get("text_bm25")),
        image_blended=_image_rows_from_payload(payload.get("image_blended")),
        text_ranked=_rows_from_payload(payload.get("text_ranked")),
        messages=list(payload.get("messages") or []),
    )


def _query_from_payload(
    payload: Optional[Dict[str, Any]], req: SearchRequest, top_k: int
) -> QueryInfo:
    if payload:
        return QueryInfo(
            k=int(payload.get("k") or top_k),
            text=payload.get("text"),
            goods_classes=list(payload.get("goods_classes") or []),
            group_codes=list(payload.get("group_codes") or []),
            variants=list(payload.get("variants") or []),
        )
    return QueryInfo(
        k=top_k,
        text=req.text,
        goods_classes=list(req.goods_classes or []),
        group_codes=list(req.group_codes or []),
        variants=list(req.variants or []),
    )


def _map_worker_result(
    result: Dict[str, Any],
    req: SearchRequest,
    top_k: int,
) -> SearchResponse:
    buckets: Dict[str, List[SearchResult]] = {
        "image_top": [],
        "image_misc": [],
        "text_top": [],
        "text_misc": [],
    }
    for candidate in result.get("candidates") or []:
        extra_meta = candidate.get("extra_meta") or {}
        bucket = extra_meta.get("bucket") or "image_top"
        bucket = bucket if bucket in buckets else "image_top"
        buckets[bucket].append(_candidate_to_result(candidate))

    debug_payload = result.get("debug") or {}
    query_payload = debug_payload.get("query") if isinstance(debug_payload, dict) else None
    pipeline_debug = debug_payload.get("pipeline") if isinstance(debug_payload, dict) else None

    return SearchResponse(
        query=_query_from_payload(query_payload, req, top_k),
        image_top=buckets["image_top"],
        image_misc=buckets["image_misc"],
        text_top=buckets["text_top"],
        text_misc=buckets["text_misc"],
        debug=_debug_from_payload(pipeline_debug),
    )


async def run_worker_search(req: SearchRequest) -> SearchResponse:
    settings = get_worker_settings()
    top_k = req.k if req.k > 0 else settings.topk_default

    if not req.image_ref and not req.image_b64:
        raise WorkerSearchUploadFailed(
            "image_ref or image_b64 is required",
            "IMAGE_MISSING",
        )

    try:
        if req.image_ref:
            image_ref = ImageRef(
                type=req.image_ref.type,
                url=req.image_ref.url,
                data=req.image_ref.data,
            )
        else:
            image_bytes = _decode_image_b64(req.image_b64)
            image_ref = build_image_ref(image_bytes)
    except ImageTransferError as exc:
        raise WorkerSearchUploadFailed(str(exc), exc.error_code) from exc
    except Exception as exc:
        raise WorkerSearchUploadFailed("image_transfer_failed", "IMAGE_TRANSFER_FAILED") from exc

    worker_id = await worker_registry.get_any_worker()
    if not worker_id:
        raise WorkerSearchUnavailable()

    job_id = str(uuid.uuid4())
    payload = _build_job_payload(req, image_ref, job_id, top_k)

    logger.info("Dispatching worker job job_id=%s worker_id=%s", job_id, worker_id)
    start = time.monotonic()
    try:
        result = await worker_registry.dispatch_job(
            worker_id, payload, timeout=settings.search_timeout_seconds
        )
    except WorkerTimeoutError as exc:
        logger.warning("Worker job timeout job_id=%s worker_id=%s", job_id, worker_id)
        raise WorkerSearchTimeout() from exc
    except (WorkerUnavailableError, WorkerDisconnectedError) as exc:
        logger.warning("Worker unavailable job_id=%s worker_id=%s", job_id, worker_id)
        raise WorkerSearchUnavailable() from exc

    elapsed_ms = int((time.monotonic() - start) * 1000)
    msg_type = (result.get("type") or "").lower()
    if msg_type == "error":
        logger.warning(
            "Worker job failed job_id=%s worker_id=%s error_code=%s",
            job_id,
            worker_id,
            result.get("error_code"),
        )
        raise WorkerSearchFailed(str(result.get("message") or "worker_error"))
    if msg_type != "result":
        logger.warning(
            "Worker job unknown response job_id=%s worker_id=%s type=%s",
            job_id,
            worker_id,
            msg_type,
        )
        raise WorkerSearchFailed("invalid_worker_response")

    response = _map_worker_result(result, req, top_k)
    try:
        response.search_id = search_cache.store(response)
    except Exception:  # pragma: no cover - cache failures should not block search
        logger.exception("Failed to store search response in cache")
    debug_payload = result.get("debug")
    if isinstance(debug_payload, dict):
        debug_payload.setdefault("elapsed_ms", elapsed_ms)
        debug_payload.setdefault("worker_id", worker_id)
    logger.info(
        "Worker job completed job_id=%s worker_id=%s elapsed_ms=%s",
        job_id,
        worker_id,
        elapsed_ms,
    )
    return response
