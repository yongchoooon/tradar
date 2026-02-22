"""In-memory job manager for async simulation runs."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
from datetime import datetime
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from app.schemas.simulation import (
    SimulationProgress,
    SimulationProgressRole,
    SimulationRequest,
    SimulationResponse,
)
from app.services.simulation_engine import run_simulation_async, SimulationCancelled


@dataclass
class SimulationJobRecord:
    request: SimulationRequest
    status: str = "pending"
    result: Optional[SimulationResponse] = None
    error: Optional[str] = None
    cancelled: bool = False
    progress: Optional[SimulationProgress] = None


class SimulationJobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, SimulationJobRecord] = {}
        self._lock = Lock()

    def enqueue(self, request: SimulationRequest) -> str:
        job_id = uuid4().hex
        total = len(request.selections or [])
        progress = SimulationProgress(
            total_candidates=total,
            roles={
                "examiner": SimulationProgressRole(done=0, total=total),
                "applicant": SimulationProgressRole(done=0, total=total),
                "examiner_reply": SimulationProgressRole(done=0, total=total),
                "reporter": SimulationProgressRole(done=0, total=total),
                "scorer": SimulationProgressRole(done=0, total=total),
                "final_reporter": SimulationProgressRole(done=0, total=1),
            },
            updated_at=None,
        )
        with self._lock:
            self._jobs[job_id] = SimulationJobRecord(request=request, progress=progress)
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
        self._update_status(job_id, "collecting")
        try:
            cancel_checker = lambda: self.is_cancelled(job_id)

            def progress_callback(event) -> None:
                if self.is_cancelled(job_id):
                    return
                if isinstance(event, str):
                    phase = event
                    if phase in {"collecting", "simulating"}:
                        self._update_status(job_id, phase)
                    return
                if not isinstance(event, dict):
                    return
                event_type = event.get("type")
                if event_type == "phase":
                    phase = event.get("status")
                    if phase in {"collecting", "simulating"}:
                        self._update_status(job_id, phase)
                    return
                if event_type == "role_complete":
                    role = event.get("role")
                    if role:
                        self._increment_progress(job_id, role)

            result = await run_simulation_async(
                record.request,
                job_id=job_id,
                cancel_checker=cancel_checker,
                progress_callback=progress_callback,
            )
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

    def _increment_progress(self, job_id: str, role: str) -> None:
        with self._lock:
            record = self._jobs.get(job_id)
            if not record or not record.progress:
                return
            role_progress = record.progress.roles.get(role)
            if not role_progress:
                return
            if role_progress.done >= role_progress.total:
                return
            role_progress.done += 1
            record.progress.updated_at = datetime.utcnow().isoformat()

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
