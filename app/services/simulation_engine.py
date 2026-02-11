"""LangGraph + KIPRIS 기반 시뮬레이션 엔진."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import mimetypes
import os
import re
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Callable, Dict, List, Optional, Sequence

import httpx

from app.schemas.simulation import (
    SimulationCandidateResult,
    SimulationRequest,
    SimulationResponse,
    SimulationSelection,
)
from app.services.kipris_client import KiprisClient, format_document_context
from app.services.langgraph_orchestrator import LangGraphOrchestrator
from app.services.log_storage import upload_text, s3_logs_enabled
from app.services.model_pricing import get_model_pricing
from dotenv import load_dotenv

logger = logging.getLogger("simulation")


load_dotenv(override=False)


class SimulationCancelled(Exception):
    """Raised when the user cancels an in-flight simulation."""


class SimulationTimeout(Exception):
    """Raised when the simulation exceeds the allowed time."""


class SimulationEngine:
    """외부 데이터를 수집하고 LangGraph 에이전트를 호출한다."""

    MAX_SELECTIONS = 20
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
        progress_callback: Optional[Callable[[str], None]] = None,
        job_id: Optional[str] = None,
    ) -> SimulationResponse:
        if not request.selections:
            raise ValueError("선택된 상표가 없습니다.")
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()

        trimmed = request.selections[: self.MAX_SELECTIONS]
        language = self._normalize_language(getattr(request, "language", None))
        debug_enabled = getattr(request, "debug", False)
        run_tag = datetime.utcnow().strftime("%Y%m%d-%H%M%S-%f")
        debug_tag = run_tag if debug_enabled else ""
        user_mark = (getattr(request, "query_title", "") or "").strip()
        user_goods = list(getattr(request, "user_goods_classes", []) or [])
        user_groups = list(getattr(request, "user_group_codes", []) or [])
        user_goods_names = list(getattr(request, "user_goods_names", []) or [])
        user_image_b64_raw = getattr(request, "user_image_b64", None)
        user_image_mime = getattr(request, "user_image_mime", None)
        user_image_ref = getattr(request, "user_image_ref", None)
        if user_image_ref:
            ref_b64, ref_mime = await self._load_user_image_ref(user_image_ref)
            if ref_b64:
                user_image_b64_raw = ref_b64
                user_image_mime = ref_mime or user_image_mime
        user_image_data_url = self._build_user_image_data_url(
            user_image_b64_raw,
            user_image_mime,
        )
        if progress_callback:
            try:
                progress_callback("collecting")
            except Exception:  # pragma: no cover - defensive
                pass
        doc_map = await self._gather_documents(trimmed)
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        if progress_callback:
            try:
                progress_callback("simulating")
            except Exception:  # pragma: no cover - defensive
                pass
        sem = asyncio.Semaphore(self.MAX_WORKERS)

        async def evaluate_with_limit(
            selection: SimulationSelection, worker_id: int
        ) -> tuple[SimulationCandidateResult, List[Dict[str, Any]]]:
            async with sem:
                if cancel_checker and cancel_checker():
                    raise SimulationCancelled()
                docs = doc_map.get(selection.application_number, {})
                return await self._evaluate(
                    selection,
                    docs,
                    debug=debug_enabled,
                    debug_tag=debug_tag,
                    user_mark=user_mark,
                    user_goods=user_goods,
                    user_groups=user_groups,
                    user_goods_names=user_goods_names,
                    user_image_data=user_image_data_url,
                    user_image_b64=user_image_b64_raw,
                    worker_id=worker_id,
                    language=language,
                    cancel_checker=cancel_checker,
                )

        tasks = []
        for idx, selection in enumerate(trimmed):
            worker_id = (idx % self.MAX_WORKERS) + 1
            tasks.append(evaluate_with_limit(selection, worker_id))
        candidates_raw = await asyncio.gather(*tasks, return_exceptions=True)
        candidates: List[SimulationCandidateResult] = []
        usage_events: List[Dict[str, Any]] = []
        for selection, result in zip(trimmed, candidates_raw):
            if isinstance(result, (SimulationCancelled, SimulationTimeout)):
                raise result
            if isinstance(result, Exception):  # pragma: no cover - defensive logging
                logger.exception(
                    "Simulation worker failed for %s: %s",
                    selection.application_number,
                    result,
                )
                continue
            candidate_result, timeline = result
            candidates.append(candidate_result)
            if timeline:
                usage_events.extend(timeline)
        candidates.sort(key=lambda item: item.conflict_score, reverse=True)

        if cancel_checker and cancel_checker():
            raise SimulationCancelled()

        high_risk = sum(1 for c in candidates if c.conflict_score >= 70)
        avg_register = mean([c.register_score for c in candidates]) if candidates else 0.0
        avg_conflict = mean([c.conflict_score for c in candidates]) if candidates else 0.0
        summary = self._build_summary(
            len(candidates),
            high_risk,
            avg_register,
            avg_conflict,
            candidates,
            language=language,
        )
        max_conflict = max((c.conflict_score for c in candidates), default=0.0)
        min_register = min((c.register_score for c in candidates), default=0.0)
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        overall_report = None
        overall_logs: List[Dict[str, str]] = []
        overall_timeline: List[Dict[str, Any]] = []
        if candidates:
            overall_report, overall_logs, overall_timeline = await self._orchestrator.summarize_overall(
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
                language=language,
            )
            if debug_enabled and debug_tag and overall_logs:
                self._log_debug_llm(debug_tag, "overall", overall_logs)
            if overall_timeline:
                for event in overall_timeline:
                    if isinstance(event, dict):
                        event.setdefault("application_number", "overall")
                        event.setdefault("variant", "overall")
                usage_events.extend(overall_timeline)
        if usage_events and s3_logs_enabled():
            self._upload_usage_bundle(
                usage_events,
                run_tag,
                request,
                total_selected=len(candidates),
                query_title=user_mark,
                job_id=job_id,
            )
        return SimulationResponse(
            total_selected=len(candidates),
            high_risk=high_risk,
            avg_conflict_score=round(avg_conflict, 1),
            avg_register_score=round(avg_register, 1),
            max_conflict_score=round(max_conflict, 1),
            min_register_score=round(min_register, 1),
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
        *,
        language: str = "ko",
    ) -> str:
        status_note = (selection.status or '').strip()
        is_en = language.lower().startswith("en")
        variant_label = "Image" if selection.variant == "image" else "Text"
        if not is_en:
            variant_label = "이미지" if selection.variant == "image" else "텍스트"
        if is_en:
            lines = [
                "[User mark]",
                f"- Name: {user_mark or '(no mark provided)'}",
            ]
            if user_goods:
                lines.append(f"- Selected classes: {', '.join(user_goods)}")
            if user_groups:
                lines.append(f"- Selected similar group codes: {', '.join(user_groups)}")
            if user_goods_names:
                lines.append("- Selected goods/services:")
                for entry in user_goods_names[:30]:
                    cleaned = (entry or '').strip()
                    if not cleaned:
                        continue
                    lines.append(f"  - {cleaned}")
            prior_title = (selection.title or "").strip() or "(No name)"
            lines += [
                "",
                "[Compared prior mark]",
                f"- Title: {prior_title} (Application No. {selection.application_number})",
                f"- Current status: {status_note or 'Status unavailable'}",
            ]
            lines.append(f"- Selection basis: user selected from {variant_label} search results")
            if selection.class_codes:
                lines.append(f"- Classes: {', '.join(selection.class_codes)}")
            goods_text = (selection.goods_services or "").strip()
            if goods_text:
                lines.append("- Goods/services summary:")
                for chunk in goods_text.split("\n"):
                    cleaned = chunk.strip()
                    if cleaned:
                        lines.append(f"  - {cleaned}")
            if selection.variant == "image":
                lines.append(
                    "- The user mark image and the prior mark image are attached. Review similarities and differences in appearance, color, and composition."
                )
            lines.append(
                "- The KIPRIS documents below show prior refusal grounds for the similar mark and serve as reference material to assess whether similar grounds could apply to the user mark."
            )
            lines.append(
                "- **Important**: Prior registered/earlier-filed marks mentioned in office actions are for reference only. Do not mention them in the direct comparison between [User mark] and [Compared prior mark]. They may be referenced only in a separate explanation such as \"prior mark refusal reasons\"."
            )
        else:
            lines = [
                "[사용자 입력 상표]",
                f"- 명칭: {user_mark or '(상표명 미입력)'}",
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
                    lines.append(f"  - {cleaned}")
            prior_title = (selection.title or "").strip() or "(상표명 없음)"
            lines += [
                "",
                "[비교 대상 유사 선행상표]",
                f"- 제목: {prior_title} (출원번호 {selection.application_number})",
                f"- 현재 상태: {status_note or '상태 정보 없음'}",
            ]
            lines.append(f"- 선정 기준: 사용자가 {variant_label} 검색 결과에서 선택한 후보")
            if selection.class_codes:
                lines.append(f"- 분류: {', '.join(selection.class_codes)}")
            goods_text = (selection.goods_services or "").strip()
            if goods_text:
                lines.append("- 지정상품 요약:")
                for chunk in goods_text.split("\n"):
                    cleaned = chunk.strip()
                    if cleaned:
                        lines.append(f"  - {cleaned}")
            if selection.variant == "image":
                lines.append("- 사용자 상표 이미지와 유사 선행상표 이미지를 함께 첨부했습니다. 외관, 색상, 구성 요소의 유사성과 차이점을 함께 검토하세요.")
            lines.append(
                "- 아래 KIPRIS 문서는 유사 선행상표가 과거에 어떤 거절사유를 지적받았는지 보여주며, 동일/유사 사유가 사용자 상표에도 적용될 수 있는지 검토하는 참고 자료입니다."
            )
            lines.append(
                "- **중요**: 의견제출통지서에 등장하는 선등록/선출원 상표는 참고용이며, [사용자 입력 상표]와 [비교 대상 유사 선행상표]를 직접 비교하는 단계에서는 절대 사용하지 마세요. 선등록 상표 언급은 '선등록 상표 거절이유'와 같은 별도 설명에서만 허용됩니다."
            )

        office = bundle.get("office_action") or {}
        rejection = bundle.get("rejection") or {}
        office_context = format_document_context(office)
        rejection_context = format_document_context(rejection)
        if office_context:
            lines.append(("[Office action]\n" if is_en else "[의견제출통지서]\n") + office_context)
        if rejection_context:
            lines.append(("[Refusal decision]\n" if is_en else "[거절결정서]\n") + rejection_context)
        return "\n\n".join(lines)

    async def _evaluate(
        self,
        selection: SimulationSelection,
        docs: Dict[str, object],
        *,
        debug: bool = False,
        debug_tag: str = "",
        user_mark: str = "",
        user_goods: List[str],
        user_groups: List[str],
        user_goods_names: List[str],
        user_image_data: Optional[str],
        user_image_b64: Optional[str],
        worker_id: int,
        language: str = "ko",
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> tuple[SimulationCandidateResult, List[Dict[str, Any]]]:
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        is_en = language.lower().startswith("en")
        variant_label = "Image" if selection.variant == "image" else "Text"
        if not is_en:
            variant_label = "이미지" if selection.variant == "image" else "텍스트"
        notes: List[str] = [
            f"{variant_label} search top candidate" if is_en else f"{variant_label} 검색 상위 후보"
        ]
        if selection.status:
            notes.append(
                f"Status: {selection.status}" if is_en else f"상태: {selection.status}"
            )
        if selection.class_codes:
            notes.append(
                f"Classes: {', '.join(selection.class_codes[:3])}"
                if is_en
                else f"분류: {', '.join(selection.class_codes[:3])}"
            )

        context_text = self._build_context(
            user_mark,
            user_goods,
            user_groups,
            user_goods_names,
            selection,
            docs or {},
            language=language,
        )
        if debug:
            self._log_debug_context(debug_tag, selection.application_number, context_text, docs)
        logger.info("Running LangGraph orchestrator for %s", selection.application_number)
        image_inputs = self._prepare_image_inputs(selection, user_image_data)
        metrics = self._build_metrics(
            user_mark=user_mark,
            selection=selection,
            user_image_b64=user_image_b64,
        )
        agent_result = await self._orchestrator.run_async(
            context=context_text,
            images=image_inputs,
            metrics=metrics,
            worker_id=worker_id,
            language=language,
        )
        if cancel_checker and cancel_checker():
            raise SimulationCancelled()
        if debug:
            self._log_debug_llm(debug_tag, selection.application_number, agent_result.get("logs", []))
        agent_summary = agent_result.get("summary")
        agent_risk = agent_result.get("risk")
        reporter_payload = agent_result.get("reporter") or {}
        reporter_markdown = reporter_payload.get("display") or reporter_payload.get("markdown")
        score_block = agent_result.get("scores") or {}
        llm_conflict_score = self._normalize_score(score_block.get("conflict_score"), 50.0)
        llm_register_score = self._normalize_score(score_block.get("register_score"), 50.0)
        llm_rationale = score_block.get("rationale")
        llm_factors = score_block.get("factors") or []
        final_conflict_score = round(llm_conflict_score, 1)
        final_register_score = round(llm_register_score, 1)
        transcript = agent_result.get("transcript", [])
        if agent_summary:
            notes.append(agent_summary)
        if agent_risk:
            notes.append(agent_risk)
        notes.append(
            (
                f"LLM evaluation: conflict risk {llm_conflict_score:.1f} pts · registrability {llm_register_score:.1f} pts"
                if is_en
                else f"LLM 평가: 충돌 위험도 {llm_conflict_score:.1f}점 · 등록 가능성 {llm_register_score:.1f}점"
            )
        )
        if llm_rationale:
            notes.append(
                f"LLM rationale: {llm_rationale}" if is_en else f"LLM 근거: {llm_rationale}"
            )
        for factor in llm_factors[:3]:
            notes.append(f"- {factor}")

        timeline = agent_result.get("timeline") or []
        if isinstance(timeline, list):
            for event in timeline:
                if isinstance(event, dict):
                    event.setdefault("application_number", selection.application_number)
                    event.setdefault("variant", selection.variant)
        else:
            timeline = []

        result = SimulationCandidateResult(
            application_number=selection.application_number,
            title=selection.title,
            variant=selection.variant,
            conflict_score=final_conflict_score,
            register_score=final_register_score,
            status=selection.status,
            class_codes=selection.class_codes,
            thumb_url=selection.thumb_url,
            notes=notes,
            agent_summary=agent_summary,
            agent_risk=agent_risk,
            transcript=transcript,
            llm_conflict_score=llm_conflict_score,
            llm_register_score=llm_register_score,
            llm_rationale=llm_rationale,
            llm_factors=list(llm_factors[:5]),
            reporter_markdown=reporter_markdown,
        )
        return result, list(timeline)

    def _build_summary(
        self,
        total: int,
        high_risk: int,
        avg_register: float,
        avg_conflict: float,
        candidates: List[SimulationCandidateResult],
        *,
        language: str = "ko",
    ) -> str:
        is_en = language.lower().startswith("en")
        if not total:
            return "No trademarks selected." if is_en else "선택된 상표가 없습니다."
        if high_risk == 0:
            if is_en:
                base = (
                    f"No high conflict-risk trademarks among {total} candidates. "
                    f"Avg conflict risk {avg_conflict:.1f} pts · Avg registrability {avg_register:.1f} pts."
                )
            else:
                base = (
                    f"총 {total}건 중 충돌 위험도가 높은 상표는 없습니다. "
                    f"평균 충돌 위험도 {avg_conflict:.1f}점 · 평균 등록 가능성 {avg_register:.1f}점입니다."
                )
        else:
            if is_en:
                base = (
                    f"{high_risk} of {total} candidates are high conflict-risk. "
                    f"Avg conflict risk {avg_conflict:.1f} pts · Avg registrability {avg_register:.1f} pts."
                )
            else:
                base = (
                    f"총 {total}건 중 {high_risk}건이 높은 충돌 위험도군입니다. "
                    f"평균 충돌 위험도 {avg_conflict:.1f}점 · 평균 등록 가능성 {avg_register:.1f}점입니다."
                )
        summaries = [c.agent_summary for c in candidates if c.agent_summary]
        if summaries:
            base += (" Key issues: " if is_en else " 주요 쟁점: ") + " / ".join(summaries[:2])
        return base

    @staticmethod
    def _normalize_language(value: Optional[str]) -> str:
        if value and str(value).lower().startswith("en"):
            return "en"
        return "ko"

    def _upload_usage_bundle(
        self,
        events: List[Dict[str, Any]],
        run_tag: str,
        request: SimulationRequest,
        *,
        total_selected: int,
        query_title: str,
        job_id: Optional[str],
    ) -> None:
        if not events:
            return

        def _parse_time(value: object) -> datetime:
            if isinstance(value, str) and value:
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    return datetime.min
            return datetime.min

        sorted_events = sorted(events, key=lambda ev: _parse_time(ev.get("start_time")))
        total_cost = 0.0
        for event in sorted_events:
            model = event.get("model")
            pricing = get_model_pricing(model) if model else {}
            in_rate = pricing.get("input", 0.0)
            out_rate = pricing.get("output", 0.0)
            input_tokens = event.get("input_tokens") or 0
            output_tokens = event.get("output_tokens") or 0
            call_cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
            total_cost += call_cost
            event["call_cost_usd"] = round(call_cost, 10)
            event["total_cost_usd"] = round(total_cost, 10)

        payload = {
            "simulation_run_id": run_tag,
            "job_id": job_id,
            "search_id": getattr(request, "search_id", None),
            "query_title": query_title,
            "total_selected": total_selected,
            "total_calls": len(sorted_events),
            "client_id": getattr(request, "client_id", None),
            "client_ip": getattr(request, "client_ip", None),
            "user_agent": getattr(request, "user_agent", None),
            "request_id": getattr(request, "request_id", None),
            "events": sorted_events,
        }
        date_tag = datetime.utcnow().strftime("%Y/%m/%d")
        upload_text(
            f"openai_ai_agent_usage/{date_tag}/{run_tag}.json",
            json.dumps(payload, ensure_ascii=False),
            content_type="application/json",
        )

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
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
        if s3_logs_enabled():
            upload_text(
                f"simulation_debug/{job_tag}/{job_tag}_{app_no}_context.json",
                text,
                content_type="application/json",
            )

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
        text = "\n".join(chunks)
        path.write_text(text, encoding="utf-8")
        if s3_logs_enabled():
            upload_text(
                f"simulation_debug/{job_tag}/{job_tag}_{app_no}_llm.txt",
                text,
                content_type="text/plain",
            )

    def _sanitize_filename(self, value: str) -> str:
        return re.sub(r"[^0-9A-Za-z_-]", "_", value or "unknown")

    async def _load_user_image_ref(
        self,
        image_ref: object,
    ) -> tuple[Optional[str], Optional[str]]:
        ref_type = (getattr(image_ref, "type", "") or "").lower()
        if ref_type in {"presigned_url", "url"}:
            url = getattr(image_ref, "url", None)
            if not url:
                return None, None
            data, mime = await self._fetch_image_bytes(url)
            if not data:
                return None, None
            encoded = base64.b64encode(data).decode("ascii")
            return encoded, mime
        if ref_type == "base64":
            data = getattr(image_ref, "data", None)
            if not data:
                return None, None
            if isinstance(data, str) and data.startswith("data:"):
                parts = data.split(",", 1)
                data = parts[1] if len(parts) == 2 else data
            return data, None
        if ref_type:
            logger.warning("Unsupported user_image_ref type=%s", ref_type)
        return None, None

    async def _fetch_image_bytes(self, url: str) -> tuple[Optional[bytes], Optional[str]]:
        timeout = httpx.Timeout(10.0, connect=5.0)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                mime = response.headers.get("content-type")
                return response.content, mime
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.warning("Failed to fetch user image from url=%s: %s", url, exc)
            return None, None

    def _build_user_image_data_url(
        self,
        data_b64: Optional[str],
        mime: Optional[str],
    ) -> Optional[str]:
        if not data_b64:
            return None
        mime_type = (mime or "image/png").split(";", 1)[0].strip() or "image/png"
        return f"data:{mime_type};base64,{data_b64}"

    def _build_metrics(
        self,
        *,
        user_mark: str,
        selection: SimulationSelection,
        user_image_b64: Optional[str],
    ) -> Dict[str, object]:
        user_norm = self._normalized_mark(user_mark)
        candidate_norm = self._normalized_mark(selection.title)
        same_title = bool(user_norm and candidate_norm and user_norm == candidate_norm)
        same_image = self._detect_same_image(user_image_b64, getattr(selection, "image_path", None))
        return {
            "same_title": same_title,
            "same_image": same_image,
            "image_similarity": selection.image_sim,
            "text_similarity": selection.text_sim,
            "variant": selection.variant,
        }

    @staticmethod
    def _normalized_mark(text: Optional[str]) -> str:
        value = (text or "").strip()
        if not value:
            return ""
        return re.sub(r"\s+", "", value).casefold()

    def _detect_same_image(self, user_image_b64: Optional[str], image_path: Optional[str]) -> bool:
        if not user_image_b64 or not image_path:
            return False
        user_bytes = self._decode_base64_bytes(user_image_b64)
        if user_bytes is None:
            return False
        candidate_path = Path(image_path)
        if not candidate_path.is_absolute():
            candidate_path = candidate_path.resolve()
        try:
            candidate_bytes = candidate_path.read_bytes()
        except OSError:
            return False
        return user_bytes == candidate_bytes

    @staticmethod
    def _decode_base64_bytes(data_str: str) -> Optional[bytes]:
        payload = data_str.strip()
        if payload.startswith("data:"):
            parts = payload.split(",", 1)
            if len(parts) == 2:
                payload = parts[1]
        try:
            return base64.b64decode(payload, validate=False)
        except (binascii.Error, ValueError):
            try:
                return base64.b64decode(payload)
            except Exception:
                return None

    def _prepare_image_inputs(
        self,
        selection: SimulationSelection,
        user_image_data: Optional[str],
    ) -> Optional[Dict[str, List[str]]]:
        images: Dict[str, List[str]] = {}
        if selection.variant == "image":
            if user_image_data:
                images.setdefault("user", []).append(user_image_data)
            candidate_data = self._load_candidate_image(selection)
            if candidate_data:
                images.setdefault("candidate", []).append(candidate_data)
        return images if images else None

    def _load_candidate_image(self, selection: SimulationSelection) -> Optional[str]:
        path_text = getattr(selection, "image_path", None)
        if not path_text:
            return None
        candidate_path = Path(path_text)
        if not candidate_path.is_absolute():
            candidate_path = candidate_path.resolve()
        try:
            data = candidate_path.read_bytes()
        except OSError:
            return None
        mime, _ = mimetypes.guess_type(str(candidate_path))
        if not mime:
            mime = "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{encoded}"

_engine = SimulationEngine()


async def run_simulation_async(
    request: SimulationRequest,
    job_id: Optional[str] = None,
    cancel_checker: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> SimulationResponse:
    return await _engine.run(
        request,
        cancel_checker=cancel_checker,
        progress_callback=progress_callback,
        job_id=job_id,
    )
