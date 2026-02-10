"""LangGraph 기반 다중 에이전트 시뮬레이션."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, TypedDict, Any, Tuple, Optional

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

try:
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    genai = None
    genai_types = None

from app.services.prompt_templates import get_prompt_bundle
from app.services.prompt_templates_base import PromptBundle
from app.services.model_pricing import get_model_pricing

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
    language: str
    prompt_bundle: PromptBundle


logger = logging.getLogger("simulation")

SIMULATION_LLM_TEMPERATURE = 1.0
GEMINI_DEFAULT_THINKING_LEVEL = "high"
GEMINI_THINKING_LEVELS = {
    "flash": {"minimal", "low", "medium", "high"},
    "pro": {"low", "high"},
}


class LangGraphOrchestrator:
    def __init__(self) -> None:
        self._model_name = os.getenv("SIMULATION_LLM_MODEL", "gpt-5-nano")
        self._temperature = SIMULATION_LLM_TEMPERATURE
        self._thinking_level = os.getenv(
            "SIMULATION_LLM_THINKING_LEVEL", GEMINI_DEFAULT_THINKING_LEVEL
        )
        self.llm: ChatOpenAI | None = None
        self._gemini_client = None
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
        language: str = "ko",
    ) -> Dict[str, Any]:
        self._refresh_llm_if_needed()
        bundle = get_prompt_bundle(language)
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
            "language": bundle.lang,
            "prompt_bundle": bundle,
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
        language: str = "ko",
    ) -> Tuple[str, List[Dict[str, str]]]:
        self._refresh_llm_if_needed()
        bundle = get_prompt_bundle(language)
        context = self._build_overall_context(
            user_mark=user_mark,
            avg_conflict=avg_conflict,
            avg_register=avg_register,
            items=items,
            bundle=bundle,
        )
        instruction = bundle.final_reporter
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
            "language": bundle.lang,
            "prompt_bundle": bundle,
        }
        response = await self._run_llm(
            role=bundle.roles["final_reporter"],
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
        bundle = state["prompt_bundle"]
        image_payloads = self._collect_image_payloads(state)
        response = await self._run_llm(
            role=bundle.roles["examiner"],
            instruction=bundle.examiner,
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, bundle.roles["examiner"], response)

    async def _applicant_node(self, state: AgentState) -> AgentState:
        bundle = state["prompt_bundle"]
        image_payloads = self._collect_image_payloads(state)
        response = await self._run_llm(
            role=bundle.roles["applicant"],
            instruction=bundle.applicant,
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, bundle.roles["applicant"], response)

    async def _examiner_reply_node(self, state: AgentState) -> AgentState:
        bundle = state["prompt_bundle"]
        response = await self._run_llm(
            role=bundle.roles["examiner_reply"],
            instruction=bundle.examiner_reply,
            state=state,
        )
        return self._append_transcript(state, bundle.roles["examiner_reply"], response)

    async def _reporter_node(self, state: AgentState) -> AgentState:
        bundle = state["prompt_bundle"]
        conversation_only = "\n".join(state.get("transcript", [])) or bundle.conversation_empty
        metrics_block = self._format_metrics_block(state, bundle)
        metrics_info = state.get("metrics") or {}
        include_image_metric, include_text_metric = self._metric_similarity_flags(metrics_info)
        copy_hint = bundle.copy_from_block.format(quant_label=bundle.quant_label)
        image_line = (
            f"- {bundle.metrics_labels['image_similarity_label']}: "
            f"<{copy_hint}>\n"
            if include_image_metric else ""
        )
        text_line = (
            f"- {bundle.metrics_labels['text_similarity_label']}: "
            f"<{copy_hint}>\n"
            if include_text_metric else ""
        )
        quant_section = ""
        reporter_context = conversation_only
        if metrics_block:
            reporter_context += f"\n\n[{bundle.quant_label}]\n" + metrics_block
        summary = await self._run_llm(
            role=bundle.roles["reporter"],
            instruction=bundle.reporter.format(
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
        new_state = self._append_transcript(state, bundle.roles["reporter"], summary)
        new_state["summary"] = summary
        new_state["reporter_only"] = {
            "markdown": summary,
            "display": display_summary,
        }
        return new_state

    async def _scorer_node(self, state: AgentState) -> AgentState:
        bundle = state["prompt_bundle"]
        reporter_markdown = state.get("reporter_only", {}).get("markdown", "")
        metrics_block = self._format_metrics_block(state, bundle)
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
            "language": state.get("language", "ko"),
            "prompt_bundle": bundle,
        }
        scorer_context = reporter_markdown
        if metrics_block:
            scorer_context += f"\n\n[{bundle.quant_label}]\n" + metrics_block
        response = await self._run_llm(
            role=bundle.roles["scorer"],
            instruction=bundle.scorer,
            state=summary_only_state,
            context_override=scorer_context,
        )
        scores = self._extract_scores(response)
        display_text = self._strip_json_from_text(response)
        new_state = self._append_transcript(state, bundle.roles["scorer"], display_text)
        new_state["risk"] = display_text
        new_state["scores"] = scores
        return new_state

    # 보조 메서드 -------------------------------------------------------------

    def _build_overall_context(
        self,
        *,
        user_mark: str,
        avg_conflict: float,
        avg_register: float,
        items: List[Dict[str, Any]],
        bundle: PromptBundle,
    ) -> str:
        def _fmt_score(value: Any, suffix: str) -> str:
            try:
                return f"{float(value):.1f}{suffix}"
            except (TypeError, ValueError):
                return f"{value}{suffix}".strip()

        if bundle.lang == "en":
            context_lines = [
                f"User mark: {user_mark or '(no mark provided)'}",
                "Prior mark summaries:",
            ]
            for idx, item in enumerate(items, start=1):
                summary_line = (item.get("summary") or "").replace("\n", " ")
                context_lines.append(
                    f"{idx}. Mark={item.get('title')} (Application No. {item.get('app_no')}) | "
                    f"Final conflict risk={_fmt_score(item.get('conflict_score'), ' pts')} | "
                    f"Final registrability={_fmt_score(item.get('register_score'), ' pts')} | "
                    f"Summary={summary_line}"
                )
            extra = (
                f"Average conflict risk: {_fmt_score(avg_conflict, ' pts')}\n"
                f"Average registrability: {_fmt_score(avg_register, ' pts')}"
            )
        else:
            context_lines = [
                f"사용자 상표: {user_mark or '(상표명 미입력)'}",
                "선행상표 요약 목록:",
            ]
            for idx, item in enumerate(items, start=1):
                summary_line = (item.get("summary") or "").replace("\n", " ")
                context_lines.append(
                    f"{idx}. 상표명={item.get('title')} (출원번호 {item.get('app_no')}) | "
                    f"최종 충돌 위험도={_fmt_score(item.get('conflict_score'), '점')} | "
                    f"최종 등록 가능성={_fmt_score(item.get('register_score'), '점')} | "
                    f"요약={summary_line}"
                )
            extra = (
                f"평균 충돌 위험도: {_fmt_score(avg_conflict, '점')}\n"
                f"평균 등록 가능성: {_fmt_score(avg_register, '점')}"
            )

        return "\n".join(context_lines) + "\n" + extra

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
        bundle = state["prompt_bundle"]
        transcript_text = transcript_override if transcript_override is not None else "\n".join(state.get("transcript", []))
        context_text = context_override if context_override is not None else state.get("context", "")
        strict_instruction = f"{instruction}\n\n{bundle.restriction_suffix}"
        context_block = f"{bundle.case_label}:\n{context_text}\n\n" if context_text else ""
        needs_transcript = bool(transcript_text and transcript_text.strip()
                                and transcript_text.strip() != (context_text or '').strip())
        transcript_block = (
            f"{bundle.conversation_label}:\n{transcript_text}\n\n"
            if needs_transcript
            else (f"{bundle.conversation_label}:\n{bundle.conversation_empty}\n\n" if not context_block else "")
        )
        human_content: Any = (
            f"{context_block}{transcript_block}{bundle.instruction_label}: {strict_instruction}"
        )
        if image_inputs:
            payload = [{"type": "text", "text": human_content}]
            for data_url in image_inputs:
                payload.append({"type": "image_url", "image_url": {"url": data_url}})
            human_content = payload

        messages = [
            SystemMessage(content=bundle.system_message_template.format(role=role)),
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

    def _format_metrics_block(self, state: AgentState, bundle: PromptBundle) -> str:
        metrics = state.get("metrics") or {}
        same_title = metrics.get("same_title")
        same_image = metrics.get("same_image")
        image_sim = metrics.get("image_similarity")
        text_sim = metrics.get("text_similarity")
        labels = bundle.metrics_labels

        def _bool_label(value: Optional[bool]) -> str:
            if value is True:
                return labels.get("same_value", "동일")
            if value is False:
                return labels.get("different_value", "불일치")
            return labels.get("unknown_value", "정보 없음")

        def _format_similarity(value: Any) -> str:
            try:
                return f"{float(value):.3f}"
            except (TypeError, ValueError):
                return labels.get("unknown_value", "정보 없음")

        lines = [
            f"{labels.get('same_title_label', '동일 상표명 여부')}: {_bool_label(same_title)}",
            f"{labels.get('same_image_label', '동일 이미지 여부')}: {_bool_label(same_image)}",
        ]
        include_image_line, include_text_line = LangGraphOrchestrator._metric_similarity_flags(metrics)
        if include_image_line:
            lines.append(f"{labels.get('image_similarity_label', '이미지 유사도')}: {_format_similarity(image_sim)}")
        if include_text_line:
            lines.append(f"{labels.get('text_similarity_label', '텍스트 유사도')}: {_format_similarity(text_sim)}")
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
        if self._is_gemini_model():
            return await self._invoke_gemini(messages)

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
        if isinstance(usage, dict) and input_tokens is None:
            input_tokens = usage.get("prompt_token_count")
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        if isinstance(usage, dict) and output_tokens is None:
            output_tokens = usage.get("candidates_token_count")
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        if isinstance(usage, dict) and total_tokens is None:
            total_tokens = usage.get("total_token_count")
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
        desired_thinking = os.getenv(
            "SIMULATION_LLM_THINKING_LEVEL", GEMINI_DEFAULT_THINKING_LEVEL
        )
        if (
            desired_model != self._model_name
            or desired_temp != self._temperature
            or desired_thinking != self._thinking_level
        ):
            self._model_name = desired_model
            self._temperature = desired_temp
            self._thinking_level = desired_thinking
            self.llm = None
            self._gemini_client = None

    def _override_temperature(self, value: float) -> None:
        self._temperature = value
        self.llm = None

    def _get_llm(self) -> ChatOpenAI:
        if self.llm is None:
            self.llm = ChatOpenAI(model=self._model_name, temperature=self._temperature)
        return self.llm

    def _is_gemini_model(self, model_name: Optional[str] = None) -> bool:
        name = (model_name or self._model_name or "").strip()
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        return name.lower().startswith("gemini-")

    @staticmethod
    def _normalize_gemini_model(model_name: str) -> str:
        model_name = (model_name or "").strip()
        if model_name.startswith("models/"):
            model_name = model_name.split("/", 1)[1]
        return model_name

    def _normalize_thinking_level(self, model_name: str, level: str | None) -> str:
        desired = (level or GEMINI_DEFAULT_THINKING_LEVEL).strip().lower()
        model = model_name.lower()
        allowed = None
        if "flash" in model:
            allowed = GEMINI_THINKING_LEVELS["flash"]
        elif "pro" in model:
            allowed = GEMINI_THINKING_LEVELS["pro"]
        if allowed and desired not in allowed:
            logger.warning(
                "Unsupported thinking_level '%s' for %s; using '%s'",
                desired,
                model_name,
                GEMINI_DEFAULT_THINKING_LEVEL,
            )
            return GEMINI_DEFAULT_THINKING_LEVEL
        return desired

    def _get_gemini_client(self):
        if genai is None or genai_types is None:
            raise RuntimeError(
                "google-genai is required for Gemini models. Install with: pip install google-genai"
            )
        if self._gemini_client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise RuntimeError("GEMINI_API_KEY is required for Gemini models")
            self._gemini_client = genai.Client(api_key=api_key)
        return self._gemini_client

    async def _invoke_gemini(self, messages: List) -> SimpleNamespace:  # type: ignore[no-untyped-def]
        client = self._get_gemini_client()
        model = self._normalize_gemini_model(self._model_name)
        thinking_level = self._normalize_thinking_level(model, self._thinking_level)
        system_text, user_parts = self._build_gemini_parts(messages)
        config_kwargs = {
            "temperature": self._temperature,
            "thinking_config": genai_types.ThinkingConfig(thinking_level=thinking_level),
        }
        if system_text:
            config_kwargs["system_instruction"] = system_text
        config = genai_types.GenerateContentConfig(**config_kwargs)

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=[{"role": "user", "parts": user_parts}],
            config=config,
        )
        try:
            text = response.text or ""
        except Exception:
            text = ""
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta and not isinstance(usage_meta, dict):
            usage_meta = {
                "prompt_token_count": getattr(usage_meta, "prompt_token_count", None),
                "candidates_token_count": getattr(usage_meta, "candidates_token_count", None),
                "total_token_count": getattr(usage_meta, "total_token_count", None),
            }
        return SimpleNamespace(content=text, usage_metadata=usage_meta)

    def _build_gemini_parts(self, messages: List) -> Tuple[str, List[Dict[str, object]]]:  # type: ignore[no-untyped-def]
        system_text = ""
        parts: List[Dict[str, object]] = []

        def _append_text(text: str) -> None:
            if text is None:
                return
            parts.append({"text": text})

        def _append_image(data_url: str) -> None:
            mime, b64 = self._parse_data_url(data_url)
            parts.append({"inline_data": {"mime_type": mime, "data": b64}})

        for msg in messages:
            if isinstance(msg, SystemMessage):
                system_text = str(msg.content or "")
                continue
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                _append_text(content)
                continue
            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    kind = item.get("type")
                    if kind == "text":
                        _append_text(str(item.get("text", "")))
                    elif kind == "image_url":
                        url = item.get("image_url", {}).get("url") if isinstance(item.get("image_url"), dict) else None
                        if isinstance(url, str) and url.startswith("data:"):
                            _append_image(url)
                        elif url:
                            logger.warning("Gemini image URL is not a data URL; skipping url=%s", url)
                continue
            _append_text(str(content))

        if not parts:
            parts.append({"text": ""})
        return system_text, parts

    @staticmethod
    def _parse_data_url(data_url: str) -> Tuple[str, str]:
        if not data_url.startswith("data:"):
            return "image/png", ""
        header, b64 = data_url.split(",", 1)
        mime = header.split(";")[0].replace("data:", "").strip() or "image/png"
        return mime, b64

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

        pattern = re.compile(r"## (정량 지표|Quantitative metrics)[\s\S]*?(?=\n## |\Z)")
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
