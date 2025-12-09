"""LangGraph 기반 다중 에이전트 시뮬레이션."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, TypedDict, Any, Tuple, Optional

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
    images: Dict[str, List[str]]
    metrics: Dict[str, Any]
    worker_id: Optional[int]
    timeline: List[Dict[str, Any]]


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

    async def run_async(
        self,
        *,
        context: str,
        images: Optional[Dict[str, List[str]]] = None,
        metrics: Optional[Dict[str, Any]] = None,
        worker_id: Optional[int] = None,
    ) -> Dict[str, Any]:
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
        load_dotenv(override=True)
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
        instruction = (
            "아래 형식을 정확히 따라 Markdown으로만 작성하세요. 평균 점수나 등록 가능성 수치는 출력하지 말고, 충돌 위험도가 높은 사례(예: 70점 이상)를 우선 정렬해 최대 6건까지만 소개하세요."
            " 고위험 항목이 부족하면 충돌 점수가 가장 높은 후보를 추가하되, 각 항목의 '주요 쟁점'은 최소 두 문장으로 작성하고 리포터가 강조한 치명적 근거를 반드시 포함하세요."
            " 내부 약어·코드명(예: Track A/B 등)은 절대 사용하지 말고, 사용자 입장에서 바로 이해할 수 있는 평이한 표현으로 작성하세요."
            " 각 항목의 '<상표명> (출원번호 <출원번호>)' 자리에는 반드시 실제 상표명과 출원번호를 그대로 넣으세요."
            " 각 항목의 모든 <>로 표시된 부분에는 반드시 실제 내용을 채워 넣으세요."
            " '권고' 항목과 마지막 '## 권고' 섹션에서는 '후속 조치 1' 같은 템플릿 문구를 쓰지 말고, 실제로 실행 가능한 조치나 전략을 요약해 문장으로 명시하세요."
            " '충돌 위험도'와 '등록 가능성' 라인은 반드시 입력된 점수를 그대로 '숫자 + 점' 형태로 출력하고, '높음/중간' 같은 추상적 표현은 사용하지 마세요.\n\n"
            "반드시 아래 형식을 정확히 따라 Markdown으로만 작성하고, 서론·맺음말 문장은 추가하지 마세요."
            "\n\n# 전체 요약\n- <2~3문장으로 전체 위험 상황과 치명적 쟁점을 구체적으로 요약>\n\n"
            "## 선행상표별 핵심 위험\n"
            "- **<상표명> (출원번호 <출원번호>)**  \n  - **충돌 위험도**: <숫자>점  \n  - **등록 가능성**: <숫자>점  \n  - **주요 쟁점**: <치명적 리스크·KIPRIS 근거를 2문장 이상으로 요약>  \n  - **권고**: <필요한 대응 또는 보정 전략>\n"
            "- **...**  \n  - **충돌 위험도**: ...  \n  - **등록 가능성**: ...  \n  - **주요 쟁점**: ...  \n  - **권고**: ...\n\n"
            "## 권고\n- <후속 조치 1>\n- <후속 조치 2>"
            "\n각 항목은 굵은 제목 → 줄바꿈된 세부 불릿 순서를 반드시 지키고, 불릿 사이에는 두 칸 공백+줄바꿈을 사용해 가독성을 확보하세요."
            " 만약 숫자 목록을 사용할 경우 반드시 '1.', '2.' 등의 형식만 허용됩니다. '1)', '2)' 등의 형식은 사용하지 마세요."
        )
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
            instruction=(
                "유사 선행상표의 심사 사례와 지정상품을 참고하여, 사용자가 입력한 상표에 대해, 가능한 거절 위험 요소를 분석하고 의견제출통지서에 준하는 논리적 평가를 작성해 주세요. "
                "반드시 아래 기준을 따르세요. \n"
                "1. 판단 방식\n"
                "  - 유사 선행상표의 과거 사례를 바탕으로 충돌 가능성이 높은 지점을 도출하되, 보정이나 대응 전략은 언급하지 않습니다.\n"
                "  - 다만 사례의 내용을 동일하게 적용하거나 사실처럼 단정하면 안 됩니다.\n"
                "  - 모든 직접 비교는 [사용자 입력 상표]와 [비교 대상 유사 선행상표] 사이에서만 수행하고, 의견제출통지서에 등장하는 타 선등록 상표는 4. 선등록 상표 거절이유 섹션에서 참고 근거로만 언급합니다.\n"
                "  - 사용자의 상표와 유사 선행상표의 표장(모양·글자·발음·관념), 지정상품의 범위 등을 비교해 논리적으로 판단합니다.\n\n"
                "2. 작성 방식\n"
                "  - 반드시 Markdown으로만 작성합니다.\n"
                "  - 각 항목은 ## 혹은 ### 소제목와 함께 숫자 목록과 불릿 목록을 적절히 활용하세요.\n\n"
                "3. 작성 목표\n"
                "  - 사용자 상표가 거절될 수 있는 잠재적 이유를 근거 중심으로 설명합니다.\n"
                "  - 각 판단 근거는 실제 특허청 심사 실무에 기반해 작성합니다.\n"
                "  - 가능한 경우 “유사 여부 판단 기준(발음·관념·외관)” 등 관례적 요소를 포함해도 괜찮습니다."
            ),
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, "심사관", response)

    async def _applicant_node(self, state: AgentState) -> AgentState:
        image_payloads = self._collect_image_payloads(state)
        response = await self._run_llm(
            role="출원인 대리인",
            instruction=(
                "심사관의 지적을 바탕으로 논리적 반박 또는 적절한 보정 방향을 제시해 주세요. "
                "심사관이 제시한 잠재적 거절 사유는 ‘가능성 제시’일 뿐이며, 이에 대해 출원인은 반박 논리, 구별 요소, 보정 방향을 명확히 제시해야 합니다. "
                "반드시 아래 기준을 따르세요. \n"
                "1. 판단 방식\n"
                "  - 심사관의 지적 중 오해 또는 과도한 추정을 짚어 반박합니다.\n"
                "  - 모든 비교 근거는 [사용자 입력 상표]와 [비교 대상 유사 선행상표] 사이에서 제시하고, 의견제출통지서의 선등록 상표는 참고 사례로만 언급합니다.\n"
                "  - 사용자의 상표가 발음, 관념, 외관, 거래 실정 등에서 충분히 구별된다는 근거를 제시합니다.\n"
                "  - 만약 보정이 유리하거나 가능하다면, 지정상품 명확화, 표현 요소 조정 등의 방향을 제시합니다.\n\n"
                "2. 작성 방식\n"
                "  - 반드시 Markdown으로만 작성합니다.\n"
                "  - 각 항목은 ## 혹은 ### 소제목와 함께 숫자 목록과 불릿 목록을 적절히 활용하세요.\n\n"
                "3. 작성 목표\n"
                "  - 각 쟁점별로 “왜 유사하지 않은지” 근거를 제시합니다.\n"
                "  - 심사관 분석이 유사 선행상표의 과거 사례에 지나치게 의존한 경우 이를 지적합니다.\n"
                "  - “본 출원은 등록 가능성이 있다”는 논리적 방향을 구축하지만 단정은 하지 않습니다."
            ),
            state=state,
            image_inputs=image_payloads,
        )
        return self._append_transcript(state, "출원인", response)

    async def _examiner_reply_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="심사관",
            instruction=(
                "출원인의 반박 중 합리적인 부분은 수용하고, 부족하거나 법적 근거가 약한 부분은 다시 반박하여 최종적인 판단 방향을 제시해 주세요."
                "앞선 대화를 그대로 반복하지 말고, 출원인이 제시한 논점별로 수용 여부와 이유를 명확히 정리한 뒤 최종 결론을 내려야 합니다."
                "충돌 판단만 내리고 보정/대응 전략은 작성하지 마세요. "
                "반드시 아래 기준을 따르세요. \n"
                "1. 판단 방식\n"
                "  - 출원인의 근거 제시가 합당하면 명시적으로 수용하고, 그 근거를 요약합니다.\n"
                "  - 법적 근거 부족, 논리적 불충분 등이 있는 부분은 다시 반박하고, 왜 유지되어야 하는지 설명합니다.\n"
                "  - 비교 판단은 일관되게 [사용자 입력 상표] vs [비교 대상 유사 선행상표]를 기본으로 하고, 의견제출통지서 속 선등록 상표는 필요 시 별도 근거로만 활용합니다.\n"
                "  - 보정이나 대응 전략은 언급하지 않습니다.\n"
                "  - 쟁점이 명백할 경우에는 단호한 결론을 내려도 됩니다.\n\n"
                "2. 작성 방식\n"
                "  - 반드시 Markdown으로만 작성합니다.\n"
                "  - 각 항목은 ## 혹은 ### 소제목와 함께 숫자 목록과 불릿 목록을 적절히 활용하세요.\n\n"
                "3. 작성 목표\n"
                "  - 쟁점을 명확히 정리하고, 반박하거나 수용하여 최종 판단 방향을 제시합니다."
            ),
            state=state,
        )
        return self._append_transcript(state, "심사관", response)

    async def _reporter_node(self, state: AgentState) -> AgentState:
        conversation_only = "\n".join(state.get("transcript", [])) or "(대화 없음)"
        metrics_block = self._format_metrics_block(state)
        metrics_info = state.get("metrics") or {}
        include_image_metric, include_text_metric = self._metric_similarity_flags(metrics_info)
        quant_instruction = (
            "## 정량 지표\n"
            "- 동일 상표명 여부: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n"
            "- 동일 이미지 여부: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n"
        )
        if include_image_metric:
            quant_instruction += "- 이미지 유사도: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n"
        if include_text_metric:
            quant_instruction += "- 텍스트 유사도: <[정량 지표] 블록의 값을 그대로 옮겨 적으세요>\n"
        quant_instruction += "\n"
        reporter_context = conversation_only
        if metrics_block:
            reporter_context += "\n\n[정량 지표]\n" + metrics_block
        summary = await self._run_llm(
            role="리포터",
            instruction=(
                "심사관과 출원인 대리인의 대화를 기반으로 아래 포맷 그대로 Markdown으로만 작성하세요."
                "\n\n# 한 줄 요약\n- <사용자 상표 vs 유사 선행상표 충돌 여부를 한 문장으로 요약>\n\n"
                "## 주요 쟁점\n"
                "1. **<쟁점명>** — <사용자 상표에 미치는 영향과 KIPRIS 근거를 2문장 이상으로 구체적으로 설명>\n"
                "2. **...** — ...\n3. **...** — ...\n\n"
                + quant_instruction
                + "모든 항목은 반드시 '번호. **<쟁점명>** — 설명' 형식을 따르고, '<쟁점명>' 전체를 굵게(**) 감싸며 치명적 위험·보정 전략을 빠짐없이 포함하세요."
                " 내부에서만 통용되는 약어나 코드명(예: Track A/B 등)은 사용하지 말고, 사용자도 즉시 이해할 수 있는 일반적인 표현으로 풀어 설명하세요."
                " 제목과 목록 외에 어떤 서론이나 마무리 문장도 작성하지 마세요."
                "<쟁점명>, <사용자 상표에 미치는 영향과 KIPRIS 근거를 2문장 이상으로 구체적으로 설명>에는 반드시 실제 내용을 채워 넣으세요."
                "만약 숫자 목록을 사용할 경우 반드시 '1.', '2.' 등의 형식만 허용됩니다. '1)', '2)' 등의 형식은 사용하지 마세요."
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
            instruction=(
                "아래는 리포터가 정리한 사용자 상표 vs 유사 선행상표 비교 요약입니다."
                " 이 요약만을 근거로 충돌 위험도와 등록 가능성을 0~100점 범위로 평가하세요."
                " 유사 선행상표의 현재 상태나 KIPRIS 세부 내용은 이미 요약에 반영되어 있다고 가정하십시오."
                " 반드시 다음 두 단계를 순서대로 따르세요:"
                " 1) 응답의 첫 줄에 JSON 객체 {conflict_score, register_score, rationale, factors[]}를 출력합니다."
                " 2) 이어서 아래 [Markdown 형식]을 반드시 정확히 지켜 항목화된 평가를 작성합니다.\n\n"
                " 평가 시에는 다음 우선순위를 반드시 고려하세요: (1) 상표명의 발음·관념·요부가 동일하거나 사실상 동일한지, (2) 사용자 입력 상표의 절대적 식별력(독창성이 부족하면 더 엄격히 평가), (3) 상표 이미지 외관 유사성, (4) 지정상품 분류와 거래 실정의 근접성."
                " 동일 상표명/동일 이미지 플래그나 이미지·텍스트 유사도 값이 제공되는 경우 이를 가장 먼저 검토하고, 동일하거나 극도로 높은 유사도라면 충돌 위험을 매우 높게, 등록 가능성을 매우 낮게 평가하는 방향으로 판단하세요."
                " 평가 시에는 각 후보의 사실관계를 냉철하게 검토하고, 치명적 충돌 근거가 명확하면 높은 충돌 위험 점수, 문제가 거의 없는 경우에는 낮은 충돌 위험 점수를 부여하세요."
                " 근거가 뚜렷하면 가급적 과감히 40~60점의 중간값에서 벗어나 높은 값 혹은 낮은 값을 점수로 부여하세요.\n\n"
                "[Markdown 형식]"
                "\n\n## 판단 요약\n- **충돌 위험도**: <숫자>점\n- **등록 가능성**: <숫자>점\n"
                "## 평가 근거\n- <핵심 근거 1>\n- <핵심 근거 2>\n"
                "## 권장 대응\n- <후속 조치 또는 대응 전략>\n"
                "제목은 반드시 '## 판단 요약', '## 평가 근거', '## 권장 대응' 순서로만 작성하고, 다른 제목이나 마무리 문구를 추가하지 마세요.\n"
                "줄글 형식의 문단을 작성하지 말고 모든 내용은 불릿 항목으로만 제시하세요.\n"
                "<숫자>, <핵심 근거 1>, <핵심 근거 2>, <후속 조치 또는 대응 전략> 부분에는 반드시 실제 내용을 채워 넣으세요.\n"
                "만약 숫자 목록을 사용할 경우 반드시 '1.', '2.' 등의 형식만 허용됩니다. '1)', '2)' 등의 형식은 사용하지 마세요."
            ),
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
        strict_instruction = (
            instruction
            + "\n\n[제한 사항]\n"
            "- 요구된 형식 외의 마무리 멘트, 후속 안내, '필요하시면...' 등의 추가 문장은 절대 포함하지 마세요.\n"
            "- 출력은 지침에 명시된 제목/목록만 포함하고, 서론이나 출력 내용 설명 문장을 쓰지 마세요.\n"
            "- 의견제출통지서에 등장하는 선등록/선출원 상표는 참고용이며, [사용자 입력 상표]와 [비교 대상 유사 선행상표]의 직접 비교 단계에서는 절대 언급하지 마세요.\n"
            "- 만약 숫자 목록을 사용할 경우 반드시 '1.', '2.' 등의 형식만 허용됩니다. '1)', '2)' 등의 형식은 사용하지 마세요."
        )
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
            SystemMessage(
                content=(
                    f"당신은 {role}입니다. 컨텍스트에는 [사용자 입력 상표]와 [비교 대상 유사 선행상표] 정보가 분리되어 있으며,"
                    " 유사 선행상표의 KIPRIS 자료는 '이 유사 선행상표가 어떤 이유로 지적되었는지'를 참고하기 위한 것입니다."
                    " 반드시 사용자 상표와 유사 선행상표를 직접 비교하면서, 과거 거절사유가 사용자 상표에도 동일하게 적용될 수 있는지,"
                    " 또는 반박/보정으로 극복 가능한지에 초점을 맞춰 한국 특허청 심사 기준으로 판단하세요."
                )
            ),
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
