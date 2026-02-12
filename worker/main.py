"""Desktop GPU worker that connects to the ECS backend via WebSocket."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import socket
import time
from dataclasses import asdict
from io import BytesIO
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlparse, urlunparse

from PIL import Image

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

from app.pipelines.search_pipeline import SearchPipeline
from app.schemas.search import SearchRequest, SearchResponse, SearchResult


logger = logging.getLogger("desktop_worker")


def _running_in_container() -> bool:
    return os.path.exists("/.dockerenv")


def _replace_hostname(url: str, hostname: str) -> str:
    parsed = urlparse(url)
    if not parsed.hostname:
        return url
    netloc = parsed.netloc
    userinfo = ""
    hostport = netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
    if ":" in hostport:
        _, port = hostport.rsplit(":", 1)
        hostport = f"{hostname}:{port}"
    else:
        hostport = hostname
    netloc = f"{userinfo}@{hostport}" if userinfo else hostport
    return urlunparse(parsed._replace(netloc=netloc))


def _shorten_url(url: str) -> str:
    parsed = urlparse(url)
    base = urlunparse(parsed._replace(query=""))
    signature = None
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == "x-amz-signature":
            signature = value
            break
    if signature:
        return f"{base}?sig={signature[:8]}…"
    return base


def _maybe_hyperlink(label: str, url: str) -> str:
    if not _bool_env("WORKER_LOG_URL_HYPERLINKS", False):
        return label
    return f"\033]8;;{url}\033\\{label}\033]8;;\033\\"


def _rewrite_localhost_env() -> None:
    if not _running_in_container():
        return
    host_gateway = os.getenv("WORKER_HOST_GATEWAY", "host.docker.internal")
    for key in ("DATABASE_URL", "OPENSEARCH_URL"):
        value = os.getenv(key)
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            os.environ[key] = _replace_hostname(value, host_gateway)
            logger.info("Rewrote %s to use %s", key, host_gateway)


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _str_env(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw is not None and raw.strip() else default


def _resolve_device(torch_module) -> str:
    device = os.getenv("EMBED_DEVICE")
    if device:
        return device
    return "cuda" if torch_module.cuda.is_available() else "cpu"


def _log_gpu_status() -> None:
    require_gpu = _bool_env("WORKER_REQUIRE_GPU", True)
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for GPU checks") from exc

    cuda_available = torch.cuda.is_available()
    device = _resolve_device(torch)
    logger.info("GPU available=%s device=%s", cuda_available, device)

    if require_gpu and (not cuda_available or not device.startswith("cuda")):
        raise RuntimeError(
            "GPU is required but not available. Ensure NVIDIA drivers/toolkit are installed "
            "or set WORKER_REQUIRE_GPU=false to allow CPU fallback."
        )
    if not require_gpu and not cuda_available:
        logger.warning("GPU not available; falling back to CPU.")
        if not os.getenv("EMBED_DEVICE") or os.getenv("EMBED_DEVICE", "").startswith("cuda"):
            os.environ["EMBED_DEVICE"] = "cpu"


def _parse_host_port(url: str, default_port: int) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or default_port
    return host, port


def _ensure_resolvable(host: str, label: str) -> None:
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        network = os.getenv("DESKTOP_COMPOSE_NETWORK", "<unset>")
        raise RuntimeError(
            f"{label} host '{host}' is not resolvable. If running Mode A, check "
            f"DESKTOP_COMPOSE_NETWORK={network} and ensure the existing compose stack is running."
        ) from exc


def _check_db_connect(timeout: float) -> None:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required")
    host, port = _parse_host_port(url, 5432)
    _ensure_resolvable(host, "DB")
    try:
        with socket.create_connection((host, port), timeout=timeout):
            logger.info("DB connectivity OK host=%s port=%s", host, port)
    except OSError as exc:
        raise RuntimeError(f"DB connection failed host={host} port={port}: {exc}") from exc


async def _check_opensearch(timeout: float) -> None:
    url = os.getenv("OPENSEARCH_URL", "").strip()
    if not url:
        raise RuntimeError("OPENSEARCH_URL is required")
    host, port = _parse_host_port(url, 9200)
    _ensure_resolvable(host, "OpenSearch")
    target = url.rstrip("/") + "/_cluster/health"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(target)
            response.raise_for_status()
        logger.info("OpenSearch connectivity OK url=%s", url)
    except Exception as exc:
        raise RuntimeError(f"OpenSearch ping failed url={url}: {exc}") from exc


async def _run_preflight_checks() -> None:
    max_attempts = int(os.getenv("WORKER_PRECHECK_MAX_ATTEMPTS", "5"))
    delay = float(os.getenv("WORKER_PRECHECK_INITIAL_DELAY_SECONDS", "1"))
    backoff = float(os.getenv("WORKER_PRECHECK_BACKOFF", "2"))
    timeout = float(os.getenv("WORKER_PRECHECK_TIMEOUT_SECONDS", "3"))
    attempt = 0

    while True:
        attempt += 1
        try:
            _check_db_connect(timeout)
            await _check_opensearch(timeout)
            logger.info("Preflight connectivity checks passed")
            return
        except Exception as exc:
            logger.error("Preflight check failed (attempt %s): %s", attempt, exc)
            if max_attempts > 0 and attempt >= max_attempts:
                raise
            await asyncio.sleep(delay)
            delay = min(delay * backoff, 30)


class DesktopWorker:
    def __init__(self) -> None:
        self._ws_url = os.getenv("WORKER_WS_URL", "").strip()
        self._worker_id = os.getenv("WORKER_ID", "desktop-1").strip()
        self._token = os.getenv("WORKER_TOKEN", "").strip()
        self._heartbeat_seconds = float(os.getenv("WORKER_HEARTBEAT_SECONDS", "20"))
        self._reconnect_min = float(os.getenv("WORKER_RECONNECT_MIN_SECONDS", "1"))
        self._reconnect_max = float(os.getenv("WORKER_RECONNECT_MAX_SECONDS", "30"))
        self._http_timeout = float(os.getenv("WORKER_HTTP_TIMEOUT_SECONDS", "20"))
        self._pipeline = SearchPipeline()
        self._http = httpx.AsyncClient(timeout=self._http_timeout)
        self._thumb_enabled = _bool_env("WORKER_THUMB_ENABLED", True)
        self._thumb_max_size = _int_env("WORKER_THUMB_MAX_SIZE", 256)
        self._thumb_max_bytes = _int_env("WORKER_THUMB_MAX_BYTES", 64 * 1024)
        self._thumb_quality = _int_env("WORKER_THUMB_QUALITY", 70)
        self._thumb_format = _str_env("WORKER_THUMB_FORMAT", "jpeg").lower()

    async def run(self) -> None:
        if not self._ws_url:
            raise RuntimeError("WORKER_WS_URL is required")
        if not self._token:
            raise RuntimeError("WORKER_TOKEN is required")

        delay = self._reconnect_min
        while True:
            try:
                await self._connect_once()
                delay = self._reconnect_min
            except Exception as exc:
                logger.warning("Worker connection failed: %s", exc)
            await asyncio.sleep(delay)
            delay = min(self._reconnect_max, delay * 2)

    async def _connect_once(self) -> None:
        logger.info("Connecting to %s as %s", self._ws_url, self._worker_id)
        async with websockets.connect(
            self._ws_url,
            ping_interval=None,
            max_size=20 * 1024 * 1024,
        ) as ws:
            await self._register(ws)
            heartbeat_task = asyncio.create_task(self._heartbeat(ws))
            try:
                async for message in ws:
                    await self._handle_message(ws, message)
            except ConnectionClosed:
                logger.warning("WebSocket closed")
            finally:
                heartbeat_task.cancel()

    async def _register(self, ws: websockets.WebSocketClientProtocol) -> None:
        payload = {
            "type": "register",
            "worker_id": self._worker_id,
            "token": self._token,
        }
        await ws.send(json.dumps(payload))

    async def _heartbeat(self, ws: websockets.WebSocketClientProtocol) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_seconds)
            try:
                await ws.send(
                    json.dumps(
                        {
                            "type": "heartbeat",
                            "worker_id": self._worker_id,
                            "ts": time.time(),
                        }
                    )
                )
            except Exception:
                return

    async def _handle_message(self, ws: websockets.WebSocketClientProtocol, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            return

        msg_type = (data.get("type") or "").lower()
        if msg_type == "registered":
            worker_id = data.get("worker_id") or self._worker_id
            logger.info("Worker registered worker_id=%s", worker_id)
            return
        if msg_type == "job":
            await self._handle_job(ws, data)
            return
        if msg_type == "ping":
            await ws.send(json.dumps({"type": "pong", "ts": time.time()}))
            return

    async def _handle_job(self, ws: websockets.WebSocketClientProtocol, data: Dict[str, Any]) -> None:
        job_id = str(data.get("job_id") or "")
        task = (data.get("task") or "").lower()
        if not job_id:
            await self._send_error(ws, job_id, "invalid_job", "job_id missing", False)
            return
        if task != "image_search":
            await self._send_error(ws, job_id, "unsupported_task", f"task={task}", False)
            return

        start = time.monotonic()
        try:
            image_bytes = await self._fetch_image(data.get("image_ref") or {})
            req = self._build_request(data, image_bytes)
            response = self._pipeline.search(req)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            result_payload = self._build_result(job_id, elapsed_ms, response)
            await ws.send(json.dumps(result_payload))
        except Exception as exc:
            logger.exception("Job failed job_id=%s", job_id)
            await self._send_error(
                ws, job_id, "processing_error", str(exc) or "processing_error", True
            )

    async def _fetch_image(self, image_ref: Dict[str, Any]) -> bytes:
        ref_type = (image_ref.get("type") or "").lower()
        if ref_type == "presigned_url":
            url = image_ref.get("url")
            if not url:
                raise ValueError("image_ref.url is required")
            label = _shorten_url(url)
            logger.info("Fetching image url=%s", _maybe_hyperlink(label, url))
            response = await self._http.get(url)
            response.raise_for_status()
            return response.content
        if ref_type == "base64":
            payload = image_ref.get("data") or ""
            return base64.b64decode(payload)
        raise ValueError(f"Unsupported image_ref type: {ref_type}")

    def _build_request(self, data: Dict[str, Any], image_bytes: bytes) -> SearchRequest:
        request_meta = data.get("request_meta") or {}
        top_k = int(data.get("top_k") or 20)
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        return SearchRequest(
            image_b64=image_b64,
            text=request_meta.get("text"),
            goods_classes=list(request_meta.get("goods_classes") or []),
            group_codes=list(request_meta.get("group_codes") or []),
            k=top_k,
            debug=bool(request_meta.get("debug")),
            variants=request_meta.get("variants"),
            use_llm_variants=bool(request_meta.get("use_llm_variants", True)),
        )

    def _build_result(self, job_id: str, elapsed_ms: int, response: SearchResponse) -> Dict[str, Any]:
        candidates: List[Dict[str, Any]] = []
        self._append_candidates(candidates, response.image_top, "image_top")
        self._append_candidates(candidates, response.image_misc, "image_misc")
        self._append_candidates(candidates, response.text_top, "text_top")
        self._append_candidates(candidates, response.text_misc, "text_misc")

        debug_payload: Optional[Dict[str, Any]] = {
            "query": asdict(response.query),
            "elapsed_ms": elapsed_ms,
            "worker_id": self._worker_id,
        }
        if response.debug:
            debug_payload["pipeline"] = asdict(response.debug)

        return {
            "type": "result",
            "job_id": job_id,
            "elapsed_ms": elapsed_ms,
            "candidates": candidates,
            "debug": debug_payload,
        }

    def _append_candidates(
        self, bucket: List[Dict[str, Any]], results: List[SearchResult], bucket_name: str
    ) -> None:
        for idx, item in enumerate(results, start=1):
            thumb_url = item.thumb_url
            if self._thumb_enabled:
                if not thumb_url or thumb_url.startswith("/media"):
                    thumb_url = self._build_thumbnail_data_url(item.image_path) or thumb_url
            bucket.append(
                {
                    "doc_id": item.trademark_id,
                    "score_image": item.image_sim,
                    "score_text": item.text_sim,
                    "title": item.title,
                    "status": item.status,
                    "nc_codes": list(item.class_codes or []),
                    "thumbnail_ref": thumb_url,
                    "extra_meta": {
                        "bucket": bucket_name,
                        "rank": idx,
                        "app_no": item.app_no,
                        "image_path": item.image_path,
                        "goods_services": item.goods_services,
                        "doi": item.doi,
                    },
                }
            )

    def _build_thumbnail_data_url(self, image_path: Optional[str]) -> Optional[str]:
        if not image_path:
            return None
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                img.thumbnail((self._thumb_max_size, self._thumb_max_size))
                buffer = BytesIO()
                if self._thumb_format == "png":
                    img.save(buffer, format="PNG", optimize=True)
                    mime = "image/png"
                else:
                    img.save(buffer, format="JPEG", quality=self._thumb_quality, optimize=True)
                    mime = "image/jpeg"
                data = buffer.getvalue()
        except Exception as exc:
            logger.debug("Thumbnail build failed path=%s error=%s", image_path, exc)
            return None

        if len(data) > self._thumb_max_bytes:
            return None
        encoded = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    async def _send_error(
        self,
        ws: websockets.WebSocketClientProtocol,
        job_id: str,
        error_code: str,
        message: str,
        retryable: bool,
    ) -> None:
        payload = {
            "type": "error",
            "job_id": job_id,
            "error_code": error_code,
            "message": message,
            "retryable": retryable,
        }
        await ws.send(json.dumps(payload))


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(name)s] %(levelname)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _rewrite_localhost_env()
    _log_gpu_status()
    await _run_preflight_checks()
    worker = DesktopWorker()
    await worker.run()


if __name__ == "__main__":
    asyncio.run(_main())
