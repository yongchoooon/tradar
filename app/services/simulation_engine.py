"""LangGraph + KIPRIS 기반 시뮬레이션 엔진."""

from __future__ import annotations

import asyncio
import logging
from statistics import mean
from typing import Dict, List, Sequence, Callable, Optional
from datetime import datetime
from pathlib import Path
import json

from app.schemas.simulation import (
    SimulationCandidateResult,
    SimulationRequest,
    SimulationResponse,
    SimulationSelection,
)
from app.services.kipris_client import KiprisClient, format_document_context
from app.services.langgraph_orchestrator import LangGraphOrchestrator

logger = logging.getLogger("simulation")


class SimulationCancelled(Exception):
    """Raised when the user cancels an in-flight simulation."""


class SimulationEngine:
    """외부 데이터를 수집하고 LangGraph 에이전트를 호출한다."""

    MAX_SELECTIONS = 40
    MAX_WORKERS = 10

    def __init__(self) -> None:
        self._client: KiprisClient | None = None
        self._doc_cache: Dict[str, Dict[str, object]] = {}
        self._orchestrator = LangGraphOrchestrator()
        self._debug_dir = Path("logs") / "simulation_debug"
        self._debug_dir.mkdir(parents=True, exist_ok=True)

    async def run(
        self,
        request: SimulationRequest,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> SimulationResponse:
        if not request.selections:
            raise ValueError("선택된 상표가 없습니다.")
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()

        trimmed = request.selections[: self.MAX_SELECTIONS]
        debug_enabled = getattr(request, "debug", False)
        job_tag = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f") if debug_enabled else ""
        user_mark = (getattr(request, "query_title", "") or "").strip()
        user_goods = list(getattr(request, "user_goods_classes", []) or [])
        user_groups = list(getattr(request, "user_group_codes", []) or [])
        user_goods_names = list(getattr(request, "user_goods_names", []) or [])
        doc_map = await self._gather_documents(trimmed)
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        sem = asyncio.Semaphore(self.MAX_WORKERS)

        async def evaluate_with_limit(selection: SimulationSelection) -> SimulationCandidateResult:
            async with sem:
                if cancel_checker and cancel_checker():
                    raise SimulationCancelled()
                docs = doc_map.get(selection.application_number, {})
                return await self._evaluate(
                    selection,
                    docs,
                    debug=debug_enabled,
                    job_tag=job_tag,
                    user_mark=user_mark,
                    user_goods=user_goods,
                    user_groups=user_groups,
                    user_goods_names=user_goods_names,
                    cancel_checker=cancel_checker,
                )

        tasks = [evaluate_with_limit(selection) for selection in trimmed]
        candidates_raw = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: List[SimulationCandidateResult] = []
        for selection, result in zip(trimmed, candidates_raw):
            if isinstance(result, SimulationCancelled):
                raise result
            if isinstance(result, Exception):  # pragma: no cover - defensive logging
                logger.exception("Simulation worker failed for %s: %s", selection.application_number, result)
                continue
            candidates.append(result)
        candidates.sort(key=lambda item: item.conflict_score, reverse=True)

        if cancel_checker and cancel_checker():
            raise SimulationCancelled()

        high_risk = sum(1 for c in candidates if c.conflict_score >= 70)
        avg_register = mean([c.register_score for c in candidates]) if candidates else 0.0
        avg_conflict = mean([c.conflict_score for c in candidates]) if candidates else 0.0
        summary = self._build_summary(len(candidates), high_risk, avg_register, avg_conflict, candidates)
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        overall_report = None
        overall_logs: List[Dict[str, str]] = []
        if candidates:
            overall_report, overall_logs = await self._orchestrator.summarize_overall(
                user_mark=user_mark,
                avg_conflict=avg_conflict,
                avg_register=avg_register,
                items=[
                    {
                        "title": c.title,
                        "app_no": c.application_number,
                        "conflict_score": c.conflict_score,
                        "register_score": c.register_score,
                        "summary": c.reporter_markdown or c.agent_summary or "",
                    }
                    for c in candidates
                ],
            )
            if debug_enabled and job_tag and overall_logs:
                self._log_debug_llm(job_tag, "overall", overall_logs)

        return SimulationResponse(
            total_selected=len(candidates),
            high_risk=high_risk,
            avg_conflict_score=round(avg_conflict, 1),
            avg_register_score=round(avg_register, 1),
            summary_text=summary,
            overall_report=overall_report,
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

    def _build_context(
        self,
        user_mark: str,
        user_goods: List[str],
        user_groups: List[str],
        user_goods_names: List[str],
        selection: SimulationSelection,
        bundle: Dict[str, object],
    ) -> str:
        status_note = (selection.status or '').strip()
        lines = [
            "[사용자 입력 상표]",
            f"- 명칭: {user_mark or '(상표명 미입력)'}",
            f"- 비교 기준: {selection.variant} 유사도 {selection.image_sim if selection.variant == 'image' else selection.text_sim}",
        ]
        if user_goods:
            lines.append(f"- 선택한 상품류: {', '.join(user_goods)}")
        if user_groups:
            lines.append(f"- 선택한 유사군: {', '.join(user_groups)}")
        if user_goods_names:
            lines.append("- 선택한 지정상품:")
            for entry in user_goods_names[:30]:
                cleaned = (entry or '').strip()
                if not cleaned:
                    continue
                lines.append(f"  · {cleaned}")
        lines += [
            "",
            "[비교 대상 선행상표]",
            f"- 제목: {selection.title} (출원번호 {selection.application_number})",
            f"- 현재 상태: {status_note or '상태 정보 없음'}",
            "- 아래 KIPRIS 문서는 선행상표가 과거에 어떤 거절사유를 지적받았는지 보여주며, 동일/유사 사유가 사용자 상표에도 적용될 수 있는지 검토하는 참고 자료입니다.",
        ]
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

    async def _evaluate(
        self,
        selection: SimulationSelection,
        docs: Dict[str, object],
        *,
        debug: bool = False,
        job_tag: str = "",
        user_mark: str = "",
        user_goods: List[str],
        user_groups: List[str],
        user_goods_names: List[str],
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> SimulationCandidateResult:
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        variant_label = "이미지" if selection.variant == "image" else "텍스트"
        similarity = selection.image_sim if selection.variant == "image" else selection.text_sim
        similarity = float(similarity or 0.0)
        similarity = max(0.0, min(similarity, 1.0))
        base_conflict_score = round(similarity * 100, 1)
        base_register_score = round(max(5.0, 100.0 - base_conflict_score * 0.7), 1)

        notes: List[str] = [f"{variant_label} 기준 유사도 {similarity:.3f}"]
        if base_conflict_score >= 85:
            notes.append("거의 동일한 수준으로 판단됩니다.")
        elif base_conflict_score >= 70:
            notes.append("충돌 위험도가 높으므로 추가 검토가 필요합니다.")
        elif base_conflict_score <= 40:
            notes.append("충돌 위험도가 낮은 편입니다.")
        if selection.status:
            notes.append(f"상태: {selection.status}")
        if selection.class_codes:
            notes.append(f"분류: {', '.join(selection.class_codes[:3])}")

        context_text = self._build_context(
            user_mark,
            user_goods,
            user_groups,
            user_goods_names,
            selection,
            docs or {},
        )
        if debug:
            self._log_debug_context(job_tag, selection.application_number, context_text, docs)
        logger.info("Running LangGraph orchestrator for %s", selection.application_number)
        agent_result = await self._orchestrator.run_async(context=context_text)
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        if debug:
            self._log_debug_llm(job_tag, selection.application_number, agent_result.get("logs", []))
        agent_summary = agent_result.get("summary")
        agent_risk = agent_result.get("risk")
        reporter_markdown = (agent_result.get("reporter") or {}).get("markdown")
        score_block = agent_result.get("scores") or {}
        llm_conflict_score = self._normalize_score(score_block.get("conflict_score"), base_conflict_score)
        llm_register_score = self._normalize_score(score_block.get("register_score"), base_register_score)
        llm_rationale = score_block.get("rationale")
        llm_factors = score_block.get("factors") or []
        final_conflict_score = round((base_conflict_score + llm_conflict_score) / 2, 1)
        final_register_score = round((base_register_score + llm_register_score) / 2, 1)
        transcript = agent_result.get("transcript", [])
        if agent_summary:
            notes.append(agent_summary)
        if agent_risk:
            notes.append(agent_risk)
        notes.append(
            f"LLM 평가: 충돌 위험도 {llm_conflict_score:.1f}% · 등록 가능성 {llm_register_score:.1f}%"
        )
        if llm_rationale:
            notes.append(f"LLM 근거: {llm_rationale}")
        for factor in llm_factors[:3]:
            notes.append(f"- {factor}")

        return SimulationCandidateResult(
            application_number=selection.application_number,
            title=selection.title,
            variant=selection.variant,
            similarity=round(similarity, 3),
            conflict_score=final_conflict_score,
            register_score=final_register_score,
            status=selection.status,
            class_codes=selection.class_codes,
            notes=notes,
            agent_summary=agent_summary,
            agent_risk=agent_risk,
            transcript=transcript,
            heuristic_conflict_score=base_conflict_score,
            heuristic_register_score=base_register_score,
            llm_conflict_score=llm_conflict_score,
            llm_register_score=llm_register_score,
            llm_rationale=llm_rationale,
            llm_factors=list(llm_factors[:5]),
            reporter_markdown=reporter_markdown,
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
                f"총 {total}건 중 충돌 위험도가 높은 상표는 없습니다. "
                f"평균 충돌 위험도 {avg_conflict:.1f}% · 평균 등록 가능성 {avg_register:.1f}%입니다."
            )
        else:
            base = (
                f"총 {total}건 중 {high_risk}건이 높은 충돌 위험도군입니다. "
                f"평균 충돌 위험도 {avg_conflict:.1f}% · 평균 등록 가능성 {avg_register:.1f}%입니다."
            )
        summaries = [c.agent_summary for c in candidates if c.agent_summary]
        if summaries:
            base += " 주요 쟁점: " + " / ".join(summaries[:2])
        return base

    def _normalize_score(self, value: object, fallback: float) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return round(fallback, 1)
        return round(max(0.0, min(100.0, score)), 1)

    def _log_debug_context(
        self,
        job_tag: str,
        app_no: str,
        context_text: str,
        docs: Dict[str, object],
    ) -> None:
        if not job_tag:
            return
        folder = self._debug_dir / job_tag
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{job_tag}_{app_no}_context.json"
        payload = {
            "application_number": app_no,
            "context": context_text,
            "documents": docs,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _log_debug_llm(
        self,
        job_tag: str,
        app_no: str,
        logs: Sequence[Dict[str, object]],
    ) -> None:
        if not job_tag or not logs:
            return
        folder = self._debug_dir / job_tag
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{job_tag}_{app_no}_llm.txt"
        chunks: List[str] = []
        for idx, entry in enumerate(logs, start=1):
            role = entry.get("role", "")
            prompt = entry.get("prompt", "")
            response = entry.get("response", "")
            chunks.append(
                f"[{idx}] 역할: {role}\n--- Prompt ---\n{prompt}\n--- Response ---\n{response}\n"
            )
        path.write_text("\n".join(chunks), encoding="utf-8")


_engine = SimulationEngine()


async def run_simulation_async(
    request: SimulationRequest,
    cancel_checker: Optional[Callable[[], bool]] = None,
) -> SimulationResponse:
    return await _engine.run(request, cancel_checker=cancel_checker)
