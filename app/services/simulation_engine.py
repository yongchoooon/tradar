"""LangGraph + KIPRIS 기반 시뮬레이션 엔진."""

from __future__ import annotations

import asyncio
import logging
from statistics import mean
from typing import Dict, List

from app.schemas.simulation import (
    SimulationCandidateResult,
    SimulationRequest,
    SimulationResponse,
    SimulationSelection,
)
from app.services.kipris_client import KiprisClient, format_document_context
from app.services.langgraph_orchestrator import LangGraphOrchestrator

logger = logging.getLogger("simulation")


class SimulationEngine:
    """외부 데이터를 수집하고 LangGraph 에이전트를 호출한다."""

    MAX_SELECTIONS = 40
    MAX_WORKERS = 4

    def __init__(self) -> None:
        self._client: KiprisClient | None = None
        self._doc_cache: Dict[str, Dict[str, object]] = {}
        self._orchestrator = LangGraphOrchestrator()

    async def run(self, request: SimulationRequest) -> SimulationResponse:
        if not request.selections:
            raise ValueError("선택된 상표가 없습니다.")

        trimmed = request.selections[: self.MAX_SELECTIONS]
        doc_map = await self._gather_documents(trimmed)
        sem = asyncio.Semaphore(self.MAX_WORKERS)

        async def evaluate_with_limit(selection: SimulationSelection) -> SimulationCandidateResult:
            async with sem:
                docs = doc_map.get(selection.application_number, {})
                return await self._evaluate(selection, docs)

        tasks = [evaluate_with_limit(selection) for selection in trimmed]
        candidates_raw = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: List[SimulationCandidateResult] = []
        for selection, result in zip(trimmed, candidates_raw):
            if isinstance(result, Exception):  # pragma: no cover - defensive logging
                logger.exception("Simulation worker failed for %s: %s", selection.application_number, result)
                continue
            candidates.append(result)
        candidates.sort(key=lambda item: item.conflict_score, reverse=True)

        high_risk = sum(1 for c in candidates if c.conflict_score >= 70)
        avg_register = mean([c.register_score for c in candidates]) if candidates else 0.0
        avg_conflict = mean([c.conflict_score for c in candidates]) if candidates else 0.0
        summary = self._build_summary(len(candidates), high_risk, avg_register, avg_conflict, candidates)

        return SimulationResponse(
            total_selected=len(candidates),
            high_risk=high_risk,
            avg_conflict_score=round(avg_conflict, 1),
            avg_register_score=round(avg_register, 1),
            summary_text=summary,
            candidates=candidates,
        )

    # ------------------------------------------------------------------ utils

    async def _gather_documents(self, selections: List[SimulationSelection]) -> Dict[str, Dict[str, object]]:
        result: Dict[str, Dict[str, object]] = {}

        async def fetch(selection: SimulationSelection) -> None:
            app_no = selection.application_number
            if app_no in self._doc_cache:
                result[app_no] = self._doc_cache[app_no]
                return
            logger.info("Fetching KIPRIS documents for %s", app_no)
            bundle = await asyncio.to_thread(self._get_client().fetch_documents, app_no)
            self._doc_cache[app_no] = bundle
            result[app_no] = bundle

        await asyncio.gather(*(fetch(selection) for selection in selections))
        return result

    def _get_client(self) -> KiprisClient:
        if self._client is None:
            self._client = KiprisClient()
        return self._client

    def _build_context(self, selection: SimulationSelection, bundle: Dict[str, object]) -> str:
        lines = [
            f"선행상표: {selection.title} (출원번호 {selection.application_number})",
            f"선택 기준: {selection.variant} 유사도 {selection.image_sim if selection.variant == 'image' else selection.text_sim}",
        ]
        if selection.status:
            lines.append(f"상태: {selection.status}")
        if selection.class_codes:
            lines.append(f"분류: {', '.join(selection.class_codes)}")

        office = bundle.get("office_action") or {}
        rejection = bundle.get("rejection") or {}
        office_context = format_document_context(office)
        rejection_context = format_document_context(rejection)
        if office_context:
            lines.append("[의견제출통지서]\n" + office_context)
        if rejection_context:
            lines.append("[거절결정서]\n" + rejection_context)
        return "\n\n".join(lines)

    async def _evaluate(self, selection: SimulationSelection, docs: Dict[str, object]) -> SimulationCandidateResult:
        variant_label = "이미지" if selection.variant == "image" else "텍스트"
        similarity = selection.image_sim if selection.variant == "image" else selection.text_sim
        similarity = float(similarity or 0.0)
        similarity = max(0.0, min(similarity, 1.0))
        conflict_score = round(similarity * 100, 1)
        register_score = round(max(5.0, 100.0 - conflict_score * 0.7), 1)

        notes: List[str] = [f"{variant_label} 기준 유사도 {similarity:.3f}"]
        if conflict_score >= 85:
            notes.append("거의 동일한 수준으로 판단됩니다.")
        elif conflict_score >= 70:
            notes.append("충돌 가능성이 높으므로 추가 검토가 필요합니다.")
        elif conflict_score <= 40:
            notes.append("충돌 위험이 낮은 편입니다.")
        if selection.status:
            notes.append(f"상태: {selection.status}")
        if selection.class_codes:
            notes.append(f"분류: {', '.join(selection.class_codes[:3])}")

        context_text = self._build_context(selection, docs or {})
        logger.info("Running LangGraph orchestrator for %s", selection.application_number)
        agent_result = await self._orchestrator.run_async(context=context_text)
        agent_summary = agent_result.get("summary")
        agent_risk = agent_result.get("risk")
        transcript = agent_result.get("transcript", [])
        if agent_summary:
            notes.append(agent_summary)
        if agent_risk:
            notes.append(agent_risk)

        return SimulationCandidateResult(
            application_number=selection.application_number,
            title=selection.title,
            variant=selection.variant,
            similarity=round(similarity, 3),
            conflict_score=conflict_score,
            register_score=register_score,
            status=selection.status,
            class_codes=selection.class_codes,
            notes=notes,
            agent_summary=agent_summary,
            agent_risk=agent_risk,
            transcript=transcript,
        )

    def _build_summary(
        self,
        total: int,
        high_risk: int,
        avg_register: float,
        avg_conflict: float,
        candidates: List[SimulationCandidateResult],
    ) -> str:
        if not total:
            return "선택된 상표가 없습니다."
        if high_risk == 0:
            base = (
                f"총 {total}건 중 충돌 위험이 높은 상표는 없습니다. "
                f"평균 충돌 위험 {avg_conflict:.1f}점 · 평균 등록 가능성 {avg_register:.1f}점입니다."
            )
        else:
            base = (
                f"총 {total}건 중 {high_risk}건이 높은 충돌 위험군입니다. "
                f"평균 충돌 위험 {avg_conflict:.1f}점 · 평균 등록 가능성 {avg_register:.1f}점입니다."
            )
        summaries = [c.agent_summary for c in candidates if c.agent_summary]
        if summaries:
            base += " 주요 쟁점: " + " / ".join(summaries[:2])
        return base


_engine = SimulationEngine()


async def run_simulation_async(request: SimulationRequest) -> SimulationResponse:
    return await _engine.run(request)
