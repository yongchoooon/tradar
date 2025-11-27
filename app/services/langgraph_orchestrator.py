"""LangGraph 기반 다중 에이전트 시뮬레이션."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, TypedDict, Any, Tuple

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph


class AgentState(TypedDict):
    context: str
    transcript: List[str]
    summary: str
    risk: str
    scores: Dict[str, Any]
    logs: List[Dict[str, str]]
    reporter_only: Dict[str, str]


logger = logging.getLogger("simulation")


class LangGraphOrchestrator:
    def __init__(self) -> None:
        model_name = os.getenv("SIMULATION_LLM_MODEL", "gpt-4o-mini")
        temperature = float(os.getenv("SIMULATION_LLM_TEMPERATURE", "1"))
        self.llm = ChatOpenAI(model=model_name, temperature=temperature)
        self._model_name = model_name
        self._temperature = temperature
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

    async def run_async(self, *, context: str) -> Dict[str, Any]:
        load_dotenv(override=True)
        self._refresh_llm_if_needed()
        state = {
            "context": context,
            "transcript": [],
            "summary": "",
            "risk": "",
            "scores": {},
            "logs": [],
            "reporter_only": {},
        }
        result = await self.graph.ainvoke(state)
        return {
            "transcript": result.get("transcript", []),
            "summary": result.get("summary", ""),
            "risk": result.get("risk", ""),
            "scores": result.get("scores", {}),
            "logs": result.get("logs", []),
            "reporter": result.get("reporter_only", {}),
        }

    async def summarize_overall(
        self,
        *,
        user_mark: str,
        avg_conflict: float,
        avg_register: float,
        items: List[Dict[str, Any]],
    ) -> Tuple[str, List[Dict[str, str]]]:
        load_dotenv(override=True)
        self._refresh_llm_if_needed()
        context_lines = [
            f"사용자 상표: {user_mark or '(상표명 미입력)'}",
            "선행상표 요약 목록:",
        ]
        for idx, item in enumerate(items, start=1):
            summary_line = (item.get('summary') or '').replace("\n", " ")
            context_lines.append(
                f"{idx}. 상표명={item.get('title')} (출원번호 {item.get('app_no')}) | 최종 충돌 위험도={item.get('conflict_score')}% | 최종 등록 가능성={item.get('register_score')}%"
                f" | 요약={summary_line}"
            )
        context = "\n".join(context_lines)
        instruction = (
            "아래 형식을 정확히 따라 Markdown으로만 작성하세요. 평균 점수나 등록 가능성 수치는 출력하지 말고, 충돌 위험도가 높은 사례(예: 70점 이상)를 우선 정렬해 최대 6건까지만 소개하세요."
            " 고위험 항목이 부족하면 충돌 점수가 가장 높은 후보를 추가하되, 각 항목의 '주요 쟁점'은 최소 두 문장으로 작성하고 리포터가 강조한 치명적 근거를 반드시 포함하세요."
            "\n\n# 전체 요약\n- <2~3문장으로 전체 위험 상황과 치명적 쟁점을 구체적으로 요약>\n\n"
            "## 선행상표별 핵심 위험\n"
            "- **상표명 (출원번호)**  \n  - 충돌 위험도: <숫자>%  \n  - 주요 쟁점: <치명적 리스크·KIPRIS 근거를 2문장 이상으로 요약>  \n  - 권고: <필요한 대응 또는 보정 전략>\n"
            "- **...**  \n  - 충돌 위험도: ...  \n  - 주요 쟁점: ...  \n  - 권고: ...\n\n"
            "## 권고\n- <후속 조치 1>\n- <후속 조치 2>"
            "\n각 항목은 굵은 제목 → 줄바꿈된 세부 불릿 순서를 반드시 지키고, 불릿 사이에는 두 칸 공백+줄바꿈을 사용해 가독성을 확보하세요."
        )
        state: AgentState = {
            "context": context,
            "transcript": [],
            "summary": "",
            "risk": "",
            "scores": {},
            "logs": [],
            "reporter_only": {},
        }
        extra = (
            f"평균 충돌 위험도: {avg_conflict:.1f}%\n"
            f"평균 등록 가능성: {avg_register:.1f}%"
        )
        state["context"] = context + "\n" + extra
        response = await self._run_llm(
            role="최종 리포터",
            instruction=instruction,
            state=state,
        )
        logs = state.get("logs", [])
        return response.strip(), list(logs)

    # 노드 정의 ---------------------------------------------------------------

    async def _examiner_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="특허청 심사관",
            instruction="수집된 자료를 바탕으로 거절이유와 법적 근거를 상세히 설명해 주세요.",
            state=state,
        )
        return self._append_transcript(state, "심사관", response)

    async def _applicant_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="출원인 대리인",
            instruction="심사관 의견에 반박하거나 보정 논리를 제시하세요.",
            state=state,
        )
        return self._append_transcript(state, "출원인", response)

    async def _examiner_reply_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="심사관",
            instruction="출원인의 주장 중 수용/반박 부분을 정리하고 최종 입장을 전달하세요.",
            state=state,
        )
        return self._append_transcript(state, "심사관", response)

    async def _reporter_node(self, state: AgentState) -> AgentState:
        conversation_only = "\n".join(state.get("transcript", [])) or "(대화 없음)"
        summary = await self._run_llm(
            role="리포터",
            instruction=(
                "심사관과 출원인 대리인의 대화를 기반으로 아래 포맷 그대로 Markdown으로만 작성하세요."
                "\n\n# 한 줄 요약\n- <사용자 상표 vs 선행상표 충돌 여부를 한 문장으로 요약>\n\n"
                "## 주요 쟁점\n"
                "1. **쟁점명** — <사용자 상표에 미치는 영향과 KIPRIS 근거를 2문장 이상으로 구체적으로 설명>\n"
                "2. **...** — ...\n3. **...** — ...\n\n"
                "모든 항목은 반드시 '번호. **쟁점명** — 설명' 형식을 따르고, '쟁점명' 전체를 굵게(**) 감싸며 치명적 위험·보정 전략을 빠짐없이 포함하세요."
            ),
            state=state,
            context_override=conversation_only,
            transcript_override=conversation_only,
        )
        summary = summary.strip()
        new_state = self._append_transcript(state, "리포터", summary)
        new_state["summary"] = summary
        new_state["reporter_only"] = {"markdown": summary}
        return new_state

    async def _scorer_node(self, state: AgentState) -> AgentState:
        reporter_markdown = state.get("reporter_only", {}).get("markdown", "")
        summary_only_state: AgentState = {
            "context": reporter_markdown,
            "transcript": [],
            "summary": reporter_markdown,
            "risk": state.get("risk", ""),
            "scores": state.get("scores", {}),
            "logs": state.get("logs", []),
            "reporter_only": state.get("reporter_only", {}),
        }
        response = await self._run_llm(
            role="채점자",
            instruction=(
                "아래는 리포터가 정리한 사용자 상표 vs 선행상표 비교 요약입니다."
                " 이 요약만을 근거로 충돌 위험도와 등록 가능성을 0~100% 범위로 평가하세요."
                " 선행상표의 현재 상태나 KIPRIS 세부 내용은 이미 요약에 반영되어 있다고 가정하십시오."
                " 반드시 다음 두 단계를 순서대로 따르세요:"
                " 1) 응답의 첫 줄에 JSON 객체 {conflict_score, register_score, rationale, factors[]}를 출력합니다."
                " 2) 이어서 아래 Markdown 형식을 정확히 지켜 항목화된 평가를 작성합니다."
                "\n\n## 판단 요약\n- **충돌 위험도**: <숫자>%\n- **등록 가능성**: <숫자>%\n"
                "## 평가 근거\n- <핵심 근거 1>\n- <핵심 근거 2>\n"
                "## 권장 대응\n- <후속 조치 또는 대응 전략>\n"
                "줄글 형식의 문단을 작성하지 말고 모든 내용은 불릿 항목으로만 제시하세요."
            ),
            state=summary_only_state,
            context_override=reporter_markdown,
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
    ) -> str:
        transcript_text = transcript_override if transcript_override is not None else "\n".join(state.get("transcript", []))
        context_text = context_override if context_override is not None else state.get("context", "")
        messages = [
            SystemMessage(
                content=(
                    f"당신은 {role}입니다. 컨텍스트에는 [사용자 입력 상표]와 [비교 대상 선행상표] 정보가 분리되어 있으며,"
                    " 선행상표의 KIPRIS 자료는 '이 선행상표가 어떤 이유로 지적되었는지'를 참고하기 위한 것입니다."
                    " 반드시 사용자 상표와 선행상표를 직접 비교하면서, 과거 거절사유가 사용자 상표에도 동일하게 적용될 수 있는지,"
                    " 또는 반박/보정으로 극복 가능한지에 초점을 맞춰 한국 특허청 심사 기준으로 판단하세요."
                )
            ),
            HumanMessage(
                content=(
                    f"사건 정보:\n{context_text}\n\n"
                    f"현재까지 대화:\n{transcript_text or '아직 대화 없음.'}\n\n"
                    f"지침: {instruction}"
                )
            ),
        ]
        response = await self._invoke_llm(messages, role)
        prompt_text = ""
        if messages:
            last = messages[-1]
            content = getattr(last, "content", "")
            prompt_text = content if isinstance(content, str) else str(content)
        self._record_log(state, role, prompt_text, response)
        return response.content.strip() if hasattr(response, "content") else str(response)

    @staticmethod
    def _append_transcript(state: AgentState, speaker: str, utterance: str) -> AgentState:
        transcript = list(state.get("transcript", []))
        transcript.append(f"[{speaker}] {utterance}")
        new_state: AgentState = {
            "context": state["context"],
            "transcript": transcript,
            "summary": state.get("summary", ""),
            "risk": state.get("risk", ""),
            "scores": state.get("scores", {}),
            "logs": state.get("logs", []),
            "reporter_only": state.get("reporter_only", {}),
        }
        return new_state

    async def _invoke_llm(self, messages: List, role: str):  # type: ignore[no-untyped-def]
        try:
            response = await self.llm.ainvoke(messages)
        except Exception as exc:
            if self._temperature_error(exc):
                logger.warning(
                    "LLM reported unsupported temperature %.2f for model %s; forcing temperature=1.0",
                    self._temperature,
                    self._model_name,
                )
                self._override_temperature(1.0)
                response = await self.llm.ainvoke(messages)
            else:
                raise
        self._log_usage(response, role)
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

    def _log_usage(self, response, role: str) -> None:  # type: ignore[no-untyped-def]
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            usage = getattr(response, "response_metadata", None)
        if not usage:
            return
        input_tokens = usage.get("input_tokens") if isinstance(usage, dict) else usage
        if isinstance(input_tokens, dict):
            input_tokens = input_tokens.get("input_tokens")
        output_tokens = usage.get("output_tokens") if isinstance(usage, dict) else None
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None

        if (
            input_tokens in {None, ""}
            and output_tokens in {None, ""}
            and total_tokens in {None, ""}
        ):
            return

        in_rate = float(os.getenv("OPENAI_RATE_INPUT_USD_PER_MTOKEN", "0.15"))
        out_rate = float(os.getenv("OPENAI_RATE_OUTPUT_USD_PER_MTOKEN", "0.60"))
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
        load_dotenv(override=True)
        desired_model = os.getenv("SIMULATION_LLM_MODEL", self._model_name)
        desired_temp = float(os.getenv("SIMULATION_LLM_TEMPERATURE", str(self._temperature)))
        if desired_model != self._model_name or desired_temp != self._temperature:
            self.llm = ChatOpenAI(model=desired_model, temperature=desired_temp)
            self._model_name = desired_model
            self._temperature = desired_temp

    def _override_temperature(self, value: float) -> None:
        self.llm = ChatOpenAI(model=self._model_name, temperature=value)
        self._temperature = value

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
