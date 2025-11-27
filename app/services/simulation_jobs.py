"""In-memory job manager for async simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.schemas.simulation import SimulationRequest, SimulationResponse
from app.services.simulation_engine import run_simulation_async, SimulationCancelled


@dataclass
class SimulationJobRecord:
    request: SimulationRequest
    status: str = "pending"
    result: Optional[SimulationResponse] = None
    error: Optional[str] = None
    cancelled: bool = False


class SimulationJobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, SimulationJobRecord] = {}
        self._lock = Lock()

    def enqueue(self, request: SimulationRequest) -> str:
        job_id = uuid4().hex
        with self._lock:
            self._jobs[job_id] = SimulationJobRecord(request=request)
        return job_id

    def get(self, job_id: str) -> Optional[SimulationJobRecord]:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Optional[SimulationJobRecord]:
        with self._lock:
            record = self._jobs.get(job_id)
            if not record:
                return None
            if record.status in {"complete", "failed", "cancelled"}:
                record.cancelled = True
                return record
            record.cancelled = True
            record.status = "cancelled"
            return record

    def is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            record = self._jobs.get(job_id)
            return bool(record and record.cancelled)

    def run_job(self, job_id: str) -> None:
        asyncio.run(self._run_job_async(job_id))

    async def _run_job_async(self, job_id: str) -> None:
        record = self.get(job_id)
        if record is None:
            return
        if record.cancelled:
            self._set_cancelled(job_id)
            return
        self._update_status(job_id, "running")
        try:
            cancel_checker = lambda: self.is_cancelled(job_id)
            result = await run_simulation_async(record.request, cancel_checker=cancel_checker)
            if self.is_cancelled(job_id):
                self._set_cancelled(job_id)
                return
            self._set_result(job_id, result)
        except SimulationCancelled:
            self._set_cancelled(job_id)
        except Exception as exc:  # pragma: no cover - defensive logging
            self._set_error(job_id, str(exc))

    def _update_status(self, job_id: str, status: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record:
                record.status = status

    def _set_result(self, job_id: str, result: SimulationResponse) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record:
                record.result = result
                record.status = "complete"
                record.error = None

    def _set_error(self, job_id: str, message: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record:
                record.error = message
                record.status = "failed"

    def _set_cancelled(self, job_id: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if record:
                record.status = "cancelled"
                record.error = None


job_manager = SimulationJobManager()
