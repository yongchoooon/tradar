"""LangGraph 기반 다중 에이전트 시뮬레이션."""

from __future__ import annotations

import os
from typing import Dict, List, TypedDict

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph


class AgentState(TypedDict):
    context: str
    transcript: List[str]
    summary: str
    risk: str


class LangGraphOrchestrator:
    def __init__(self) -> None:
        model_name = os.getenv("SIMULATION_LLM_MODEL", "gpt-4o-mini")
        temperature = float(os.getenv("SIMULATION_LLM_TEMPERATURE", "0.2"))
        self.llm = ChatOpenAI(model=model_name, temperature=temperature)
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

    async def run_async(self, *, context: str) -> Dict[str, str]:
        state = {
            "context": context,
            "transcript": [],
            "summary": "",
            "risk": "",
        }
        result = await self.graph.ainvoke(state)
        return {
            "transcript": result.get("transcript", []),
            "summary": result.get("summary", ""),
            "risk": result.get("risk", ""),
        }

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
        summary = await self._run_llm(
            role="리포터",
            instruction=(
                "심사관과 출원인의 대화에서 중요한 쟁점을 1~3개의 불릿으로 정리하고,"
                " 각 항목은 '표장/쟁점 - 이유' 형식으로 작성하세요."
            ),
            state=state,
        )
        new_state = self._append_transcript(state, "리포터", summary)
        new_state["summary"] = summary
        return new_state

    async def _scorer_node(self, state: AgentState) -> AgentState:
        response = await self._run_llm(
            role="채점자",
            instruction="전체 대화를 기반으로 등록 가능성과 침해 위험을 한 문단으로 평가하고, 사용자에게 필요한 조치 또는 권고를 제시하세요.",
            state=state,
        )
        new_state = self._append_transcript(state, "채점자", response)
        new_state["risk"] = response
        return new_state

    # 보조 메서드 -------------------------------------------------------------

    async def _run_llm(self, *, role: str, instruction: str, state: AgentState) -> str:
        transcript_text = "\n".join(state.get("transcript", []))
        messages = [
            SystemMessage(
                content=(
                    f"당신은 {role}입니다. 사용자는 상표 등록 가능성 평가를 위해 선행상표 정보를 제공했습니다."
                    f"다음 정보를 기반으로 한국 특허청 관점에서 응답하세요."
                )
            ),
            HumanMessage(
                content=(
                    f"사건 정보:\n{state['context']}\n\n"
                    f"현재까지 대화:\n{transcript_text or '아직 대화 없음.'}\n\n"
                    f"지침: {instruction}"
                )
            ),
        ]
        response = await self.llm.ainvoke(messages)
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
        }
        return new_state
