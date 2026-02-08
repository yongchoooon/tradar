"""LangGraph 기반 다중 에이전트 시뮬레이션."""

from __future__ import annotations

import logging
import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, TypedDict, Any, Tuple, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.services.prompt_templates import (
    LLM_RESTRICTION_SUFFIX,
    FINAL_REPORTER_PROMPT,
    EXAMINER_PROMPT,
    APPLICANT_PROMPT,
    EXAMINER_REPLY_PROMPT,
    REPORTER_PROMPT,
    SCORER_PROMPT,
    SYSTEM_MESSAGE_TEMPLATE,
)
from app.services.model_pricing import get_model_pricing
from app.services.log_storage import upload_text, s3_logs_enabled

load_dotenv(override=False)


class AgentState(TypedDict):
    context: str
    transcript: List[str]
    summary: str
    risk: str
    scores: Dict[str, Any]
    logs: List[Dict[str, str]]
    reporter_only: Dict[str, str]
    images: Dict[str, List[str]]
    metrics: Dict[str, Any]
    worker_id: Optional[int]
    timeline: List[Dict[str, Any]]


logger = logging.getLogger("simulation")

SIMULATION_LLM_TEMPERATURE = 1.0


class LangGraphOrchestrator:
    def __init__(self) -> None:
        self._model_name = os.getenv("SIMULATION_LLM_MODEL", "gpt-5-nano")
        self._temperature = SIMULATION_LLM_TEMPERATURE
        self.llm: ChatOpenAI | None = None
        self._usage_log_path = self._ensure_usage_log()
        self._running_total = self._load_existing_usage_total()
        workflow = StateGraph(AgentState)
        workflow.add_node("examiner", self._examiner_node)
        workflow.add_node("applicant", self._applicant_node)
        workflow.add_node("examiner_reply", self._examiner_reply_node)
        workflow.add_node("reporter", self._reporter_node)
        workflow.add_node("scorer", self._scorer_node)
        workflow.set_entry_point("examiner")
        workflow.add_edge("examiner", "applicant")
        workflow.add_edge("applicant", "examiner_reply")
        workflow.add_edge("examiner_reply", "reporter")
        workflow.add_edge("reporter", "scorer")
        workflow.add_edge("scorer", END)
        self.graph = workflow.compile()

    async def run_async(
        self,
        *,
        context: str,
        images: Optional[Dict[str, List[str]]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        worker_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._refresh_llm_if_needed()
        state = {
            "context": context,
            "transcript": [],
            "summary": "",
            "risk": "",
            "scores": {},
            "logs": [],
            "reporter_only": {},
            "images": images or {},
            "metrics": metrics or {},
            "worker_id": worker_id,
            "timeline": [],
        }
        result = await self.graph.ainvoke(state)
        return {
            "transcript": result.get("transcript", []),
            "summary": result.get("summary", ""),
            "risk": result.get("risk", ""),
            "scores": result.get("scores", {}),
            "logs": result.get("logs", []),
            "reporter": result.get("reporter_only", {}),
            "timeline": result.get("timeline", []),
        }

    async def summarize_overall(
        self,
        *,
        user_mark: str,
        avg_conflict: float,
        avg_register: float,
        items: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, str]]]:
        self._refresh_llm_if_needed()
        context_lines = [
            f"사용자 상표: {user_mark or '(상표명 미입력)'}",
            "선행상표 요약 목록:",
        ]
        for idx, item in enumerate(items, start=1):
            summary_line = (item.get('summary') or '').replace("\n", " ")
            context_lines.append(
                f"{idx}. 상표명={item.get('title')} (출원번호 {item.get('app_no')}) | 최종 충돌 위험도={item.get('conflict_score')}점 | 최종 등록 가능성={item.get('register_score')}점"
                f" | 요약={summary_line}"
            )
        context = "\n".join(context_lines)
        instruction = FINAL_REPORTER_PROMPT
        state: AgentState = {
            "context": context,
            "transcript": [],
            "summary": "",
            "risk": "",
            "scores": {},
            "logs": [],
            "reporter_only": {},
            "images": {},
            "metrics": {},
            "worker_id": 0,
            "timeline": [],
        }
        extra = (
            f"평균 충돌 위험도: {avg_conflict:.1f}점\n"
            f"평균 등록 가능성: {avg_register:.1f}점"
        )
        state["context"] = context + "\n" + extra
        response = await self._run_llm(
            role="최종 리포터",
            instruction=instruction,
            state=state,
        )
        state.setdefault("worker_id", 0)
        state.setdefault("timeline", [])
        logs = state.get("logs", [])
        timeline = state.get("timeline", [])
        return response.strip(), list(logs), list(timeline)

    # 노드 정의 ---------------------------------------------------------------

    async def _examiner_node(self, state: AgentState) -> AgentState:
        image_payloads = self._collect_image_payloads(state)
        response = await self._run_llm(
            role="특허청 심사관",
            instruction=EXAMINER_PROMPT,
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, "심사관", response)

    async def _applicant_node(self, state: AgentState) -> AgentState:
        image_payloads = self._collect_image_payloads(state)
        response = await self._run_llm(
            role="출원인 대리인",
            instruction=APPLICANT_PROMPT,
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, "출원인", response)

    async def _examiner_reply_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="심사관",
            instruction=EXAMINER_REPLY_PROMPT,
            state=state,
        )
        return self._append_transcript(state, "심사관", response)

    async def _reporter_node(self, state: AgentState) -> AgentState:
        conversation_only = "\n".join(state.get("transcript", [])) or "(대화 없음)"
        metrics_block = self._format_metrics_block(state)
        metrics_info = state.get("metrics") or {}
        include_image_metric, include_text_metric = self._metric_similarity_flags(metrics_info)
        image_line = "- 이미지 유사도: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n" if include_image_metric else ""
        text_line = "- 텍스트 유사도: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n" if include_text_metric else ""
        quant_section = ""
        reporter_context = conversation_only
        if metrics_block:
            reporter_context += "\n\n[정량 지표]\n" + metrics_block
        summary = await self._run_llm(
            role="리포터",
            instruction=REPORTER_PROMPT.format(
                image_line=image_line,
                text_line=text_line,
                quant_section=quant_section,
            ),
            state=state,
            context_override=reporter_context,
            transcript_override=reporter_context,
        )
        summary = summary.strip()
        display_summary = self._strip_quant_section(summary)
        new_state = self._append_transcript(state, "리포터", summary)
        new_state["summary"] = summary
        new_state["reporter_only"] = {
            "markdown": summary,
            "display": display_summary,
        }
        return new_state

    async def _scorer_node(self, state: AgentState) -> AgentState:
        reporter_markdown = state.get("reporter_only", {}).get("markdown", "")
        metrics_block = self._format_metrics_block(state)
        summary_only_state: AgentState = {
            "context": reporter_markdown,
            "transcript": [],
            "summary": reporter_markdown,
            "risk": state.get("risk", ""),
            "scores": state.get("scores", {}),
            "logs": state.get("logs", []),
            "reporter_only": state.get("reporter_only", {}),
            "images": state.get("images", {}),
            "metrics": state.get("metrics", {}),
            "worker_id": state.get("worker_id"),
            "timeline": state.get("timeline", []),
        }
        scorer_context = reporter_markdown
        if metrics_block:
            scorer_context += "\n\n[정량 지표]\n" + metrics_block
        response = await self._run_llm(
            role="채점자",
            instruction=SCORER_PROMPT,
            state=summary_only_state,
            context_override=scorer_context,
        )
        scores = self._extract_scores(response)
        display_text = self._strip_json_from_text(response)
        new_state = self._append_transcript(state, "채점자", display_text)
        new_state["risk"] = display_text
        new_state["scores"] = scores
        return new_state

    # 보조 메서드 -------------------------------------------------------------

    async def _run_llm(
        self,
        *,
        role: str,
        instruction: str,
        state: AgentState,
        context_override: str | None = None,
        transcript_override: str | None = None,
        image_inputs: Optional[List[str]] = None,
    ) -> str:
        transcript_text = transcript_override if transcript_override is not None else "\n".join(state.get("transcript", []))
        context_text = context_override if context_override is not None else state.get("context", "")
        strict_instruction = f"{instruction}\n\n{LLM_RESTRICTION_SUFFIX}"
        context_block = f"사건 정보:\n{context_text}\n\n" if context_text else ""
        needs_transcript = bool(transcript_text and transcript_text.strip()
                                and transcript_text.strip() != (context_text or '').strip())
        transcript_block = (
            f"현재까지 대화:\n{transcript_text}\n\n"
            if needs_transcript
            else ("현재까지 대화:\n아직 대화 없음.\n\n" if not context_block else "")
        )
        human_content: Any = (
            f"{context_block}{transcript_block}지침: {strict_instruction}"
        )
        if image_inputs:
            payload = [{"type": "text", "text": human_content}]
            for data_url in image_inputs:
                payload.append({"type": "image_url", "image_url": {"url": data_url}})
            human_content = payload

        messages = [
            SystemMessage(content=SYSTEM_MESSAGE_TEMPLATE.format(role=role)),
            HumanMessage(content=human_content),
        ]
        start_time = datetime.utcnow()
        response = await self._invoke_llm(messages, role)
        end_time = datetime.utcnow()
        usage_counts = self._log_usage(response, role)
        prompt_text = ""
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            prompt_text = content if isinstance(content, str) else str(content)
        self._record_log(state, role, prompt_text, response)
        self._record_timeline_event(
            state,
            role=role,
            start_time=start_time,
            end_time=end_time,
            usage_counts=usage_counts,
        )
        return response.content.strip() if hasattr(response, "content") else str(response)

    @staticmethod
    def _collect_image_payloads(state: AgentState) -> List[str]:
        images = state.get("images") or {}
        payloads: List[str] = []
        for key in ("user", "candidate"):
            entries = images.get(key)
            if entries:
                payloads.extend(entries)
        return payloads

    @staticmethod
    def _append_transcript(state: AgentState, speaker: str, utterance: str) -> AgentState:
        transcript = list(state.get("transcript", []))
        transcript.append(f"[{speaker}]\n{utterance}")
        new_state: AgentState = {
            "context": state["context"],
            "transcript": transcript,
            "summary": state.get("summary", ""),
            "risk": state.get("risk", ""),
            "scores": state.get("scores", {}),
            "logs": state.get("logs", []),
            "reporter_only": state.get("reporter_only", {}),
            "images": state.get("images", {}),
            "metrics": state.get("metrics", {}),
            "worker_id": state.get("worker_id"),
            "timeline": state.get("timeline", []),
        }
        return new_state

    @staticmethod
    def _format_metrics_block(state: AgentState) -> str:
        metrics = state.get("metrics") or {}
        same_title = metrics.get("same_title")
        same_image = metrics.get("same_image")
        image_sim = metrics.get("image_similarity")
        text_sim = metrics.get("text_similarity")

        def _bool_label(value: Optional[bool]) -> str:
            if value is True:
                return "동일"
            if value is False:
                return "불일치"
            return "정보 없음"

        def _format_similarity(value: Any) -> str:
            try:
                return f"{float(value):.3f}"
            except (TypeError, ValueError):
                return "정보 없음"

        lines = [
            f"동일 상표명 여부: {_bool_label(same_title)}",
            f"동일 이미지 여부: {_bool_label(same_image)}",
        ]
        include_image_line, include_text_line = LangGraphOrchestrator._metric_similarity_flags(metrics)
        if include_image_line:
            lines.append(f"이미지 유사도: {_format_similarity(image_sim)}")
        if include_text_line:
            lines.append(f"텍스트 유사도: {_format_similarity(text_sim)}")
        return "\n".join(lines)

    @staticmethod
    def _metric_similarity_flags(metrics: Dict[str, Any]) -> Tuple[bool, bool]:
        variant = metrics.get("variant")
        image_sim = metrics.get("image_similarity")
        text_sim = metrics.get("text_similarity")
        include_image_line = bool(variant == "image" and image_sim is not None)
        include_text_line = bool(variant == "text" and text_sim is not None)
        if not variant:
            include_image_line = image_sim is not None
            include_text_line = text_sim is not None
        return include_image_line, include_text_line

    async def _invoke_llm(self, messages: List, role: str):  # type: ignore[no-untyped-def]
        llm = self._get_llm()
        try:
            response = await llm.ainvoke(messages)
        except Exception as exc:
            if self._temperature_error(exc):
                logger.warning(
                    "LLM reported unsupported temperature %.2f for model %s; forcing temperature=1.0",
                    self._temperature,
                    self._model_name,
                )
                self._override_temperature(1.0)
                response = await self._get_llm().ainvoke(messages)
            else:
                raise
        return response

    def _ensure_usage_log(self) -> Path:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "openai_ai_agent_usage.csv"
        if not path.exists():
            path.write_text(
                "timestamp,model,role,input_tokens,output_tokens,total_tokens,call_cost_usd,total_cost_usd\n",
                encoding="utf-8",
            )
        return path

    def _log_usage(
        self,
        response,
        role: str,
    ) -> Tuple[Optional[int], Optional[int], Optional[int]] | None:  # type: ignore[no-untyped-def]
        counts = self._extract_usage_counts(response)
        if not counts:
            return None
        input_tokens, output_tokens, total_tokens = counts
        if (
            input_tokens in {None, ""}
            and output_tokens in {None, ""}
            and total_tokens in {None, ""}
        ):
            return counts

        pricing = get_model_pricing(self._model_name)
        in_rate = pricing.get("input", 0.0)
        out_rate = pricing.get("output", 0.0)
        input_cost = (input_tokens or 0) * (in_rate / 1_000_000)
        output_cost = (output_tokens or 0) * (out_rate / 1_000_000)
        call_cost = input_cost + output_cost
        self._running_total += call_cost

        timestamp = datetime.utcnow().isoformat()
        line = (
            f"{timestamp},"
            f"{self._model_name},"
            f"{role},"
            f"{input_tokens if input_tokens is not None else ''},"
            f"{output_tokens if output_tokens is not None else ''},"
            f"{total_tokens if total_tokens is not None else ''},"
            f"{call_cost:.10f},"
            f"{self._running_total:.10f}\n"
        )
        with self._usage_log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
        if s3_logs_enabled():
            date_tag = datetime.utcnow().strftime("%Y/%m/%d")
            entry_id = uuid.uuid4().hex
            payload = {
                "timestamp": timestamp,
                "model": self._model_name,
                "role": role,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "call_cost_usd": call_cost,
                "total_cost_usd": self._running_total,
            }
            upload_text(
                f"openai_ai_agent_usage/{date_tag}/{entry_id}.json",
                json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
            )
        return counts

    @staticmethod
    def _extract_usage_counts(response) -> Tuple[Optional[int], Optional[int], Optional[int]] | None:  # type: ignore[no-untyped-def]
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            usage = getattr(response, "response_metadata", None)
        if not usage:
            return None
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else usage
        if isinstance(input_tokens, dict):
            input_tokens = input_tokens.get("input_tokens")
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        return input_tokens, output_tokens, total_tokens

    def _load_existing_usage_total(self) -> float:
        try:
            with self._usage_log_path.open("r", encoding="utf-8") as fh:
                last_line = None
                for line in fh:
                    if line.strip():
                        last_line = line.strip()
            if not last_line or last_line.startswith("timestamp"):
                return 0.0
            parts = last_line.split(",")
            if len(parts) >= 8:
                return float(parts[-1])
        except FileNotFoundError:
            return 0.0
        except ValueError:
            return 0.0
        return 0.0

    def _refresh_llm_if_needed(self) -> None:
        desired_model = os.getenv("SIMULATION_LLM_MODEL", self._model_name)
        desired_temp = SIMULATION_LLM_TEMPERATURE
        if desired_model != self._model_name or desired_temp != self._temperature:
            self._model_name = desired_model
            self._temperature = desired_temp
            self.llm = None

    def _override_temperature(self, value: float) -> None:
        self._temperature = value
        self.llm = None

    def _get_llm(self) -> ChatOpenAI:
        if self.llm is None:
            self.llm = ChatOpenAI(model=self._model_name, temperature=self._temperature)
        return self.llm

    @staticmethod
    def _temperature_error(exc: Exception) -> bool:
        message = str(exc)
        return "temperature" in message and "Only the default (1) value" in message

    def _extract_scores(self, text: str) -> Dict[str, Any]:
        import json
        import re

        match = re.search(r"\{.*?\}", text, re.S)
        if not match:
            return {}
        snippet = match.group(0)
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError:
            return {}
        scores: Dict[str, Any] = {}
        conflict = data.get("conflict_score")
        register = data.get("register_score")
        scores["conflict_score"] = self._clamp_score(conflict)
        scores["register_score"] = self._clamp_score(register)
        scores["rationale"] = data.get("rationale") or data.get("reasoning")
        factors = data.get("factors")
        if isinstance(factors, list):
            scores["factors"] = [str(item) for item in factors if str(item).strip()]
        else:
            scores["factors"] = []
        return scores

    @staticmethod
    def _strip_json_from_text(text: str) -> str:
        import re

        cleaned = re.sub(r"\{.*?\}", "", text, flags=re.S).strip()
        return cleaned or text

    @staticmethod
    def _strip_quant_section(summary: str) -> str:
        import re

        pattern = re.compile(r"## 정량 지표[\s\S]*?(?=\n## |\Z)")
        stripped = pattern.sub("", summary).strip()
        return stripped or summary

    @staticmethod
    def _clamp_score(value: Any) -> float:
        try:
            num = float(value)
        except (TypeError, ValueError):
            return 0.0
        return float(max(0.0, min(100.0, num)))

    @staticmethod
    def _record_log(state: AgentState, role: str, prompt: str, response) -> None:
        entries = state.get("logs")
        if not isinstance(entries, list):
            return
        content = response.content if hasattr(response, "content") else str(response)
        entries.append(
            {
                "role": role,
                "prompt": prompt,
                "response": content,
            }
        )

    def _record_timeline_event(
        self,
        state: AgentState,
        *,
        role: str,
        start_time: datetime,
        end_time: datetime,
        usage_counts: Tuple[Optional[int], Optional[int], Optional[int]] | None,
    ) -> None:
        events = state.get("timeline")
        if not isinstance(events, list):
            return
        elapsed_ms = (end_time - start_time).total_seconds() * 1000.0
        input_tokens: Optional[int] = None
        output_tokens: Optional[int] = None
        total_tokens: Optional[int] = None
        if usage_counts:
            input_tokens, output_tokens, total_tokens = usage_counts
        events.append(
            {
                "worker_id": state.get("worker_id"),
                "role": role,
                "model": self._model_name,
                "start_time": start_time.isoformat(),
                "end_time": end_time.isoformat(),
                "elapsed_ms": round(elapsed_ms, 3),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
            }
        )
