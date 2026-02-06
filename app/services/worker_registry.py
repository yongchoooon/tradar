"""In-memory registry for desktop worker connections and pending jobs."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class WorkerRegistryError(Exception):
    """Base worker registry error."""


class WorkerUnavailableError(WorkerRegistryError):
    """No worker available for dispatch."""


class WorkerDisconnectedError(WorkerRegistryError):
    """Worker disconnected during job processing."""


class WorkerTimeoutError(WorkerRegistryError):
    """Worker job timed out."""


@dataclass
class WorkerConnection:
    worker_id: str
    websocket: WebSocket
    connected_at: float
    last_seen: float


@dataclass
class PendingJob:
    future: asyncio.Future
    worker_id: str
    created_at: float


class WorkerRegistry:
    def __init__(self) -> None:
        self._workers: Dict[str, WorkerConnection] = {}
        self._pending: Dict[str, PendingJob] = {}
        self._lock = asyncio.Lock()

    async def register(self, worker_id: str, websocket: WebSocket) -> None:
        now = time.monotonic()
        async with self._lock:
            self._workers[worker_id] = WorkerConnection(
                worker_id=worker_id,
                websocket=websocket,
                connected_at=now,
                last_seen=now,
            )
        logger.info("Worker connected worker_id=%s", worker_id)

    async def unregister(self, worker_id: str) -> None:
        async with self._lock:
            self._workers.pop(worker_id, None)
            to_fail = [
                job_id
                for job_id, pending in self._pending.items()
                if pending.worker_id == worker_id
            ]
        if to_fail:
            for job_id in to_fail:
                pending = self._pending.pop(job_id, None)
                if pending and not pending.future.done():
                    pending.future.set_exception(WorkerDisconnectedError())
        logger.info("Worker disconnected worker_id=%s", worker_id)

    async def get_any_worker(self) -> Optional[str]:
        async with self._lock:
            for worker_id in self._workers.keys():
                return worker_id
        return None

    async def dispatch_job(
        self, worker_id: str, payload: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        async with self._lock:
            worker = self._workers.get(worker_id)
            if not worker:
                raise WorkerUnavailableError()
            loop = asyncio.get_running_loop()
            job_id = payload.get("job_id")
            if not job_id:
                raise ValueError("job_id is required for dispatch")
            future: asyncio.Future = loop.create_future()
            self._pending[str(job_id)] = PendingJob(
                future=future, worker_id=worker_id, created_at=time.monotonic()
            )

        try:
            await worker.websocket.send_json(payload)
        except Exception as exc:
            async with self._lock:
                self._pending.pop(str(job_id), None)
            logger.warning("Failed to send job %s to worker %s: %s", job_id, worker_id, exc)
            raise WorkerUnavailableError() from exc

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            async with self._lock:
                self._pending.pop(str(job_id), None)
            raise WorkerTimeoutError() from exc
        finally:
            async with self._lock:
                self._pending.pop(str(job_id), None)
        return result

    async def handle_message(self, worker_id: str, message: Dict[str, Any]) -> None:
        msg_type = (message.get("type") or "").lower()
        now = time.monotonic()
        async with self._lock:
            worker = self._workers.get(worker_id)
            if worker:
                worker.last_seen = now
            job_id = message.get("job_id")
            pending = self._pending.get(str(job_id)) if job_id else None

        if msg_type in {"result", "error"} and pending:
            if not pending.future.done():
                pending.future.set_result(message)
            return

        if msg_type in {"heartbeat", "pong"}:
            return

        if msg_type and msg_type not in {"result", "error", "heartbeat", "pong", "ping"}:
            logger.debug("Unhandled worker message type=%s worker_id=%s", msg_type, worker_id)


worker_registry = WorkerRegistry()
