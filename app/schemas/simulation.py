"""Schemas for AI agent simulation requests/responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

try:  # pragma: no cover
    from pydantic.dataclasses import dataclass as pydantic_dataclass  # type: ignore
except Exception:  # pragma: no cover
    pydantic_dataclass = dataclass


VariantType = Literal["image", "text"]


@pydantic_dataclass
class SimulationSelection:
    application_number: str
    title: str
    variant: VariantType
    image_sim: Optional[float] = None
    text_sim: Optional[float] = None
    status: Optional[str] = None
    class_codes: List[str] = field(default_factory=list)


@pydantic_dataclass
class SimulationRequest:
    selections: List[SimulationSelection]
    debug: bool = False
    query_title: Optional[str] = None
    user_goods_classes: List[str] = field(default_factory=list)
    user_group_codes: List[str] = field(default_factory=list)
    user_goods_names: List[str] = field(default_factory=list)


@pydantic_dataclass
class SimulationCandidateResult:
    application_number: str
    title: str
    variant: VariantType
    similarity: float
    conflict_score: float
    register_score: float
    status: Optional[str]
    class_codes: List[str]
    notes: List[str] = field(default_factory=list)
    agent_summary: Optional[str] = None
    agent_risk: Optional[str] = None
    transcript: List[str] = field(default_factory=list)
    heuristic_conflict_score: float = 0.0
    heuristic_register_score: float = 0.0
    llm_conflict_score: float = 0.0
    llm_register_score: float = 0.0
    llm_rationale: Optional[str] = None
    llm_factors: List[str] = field(default_factory=list)
    reporter_markdown: Optional[str] = None


@pydantic_dataclass
class SimulationResponse:
    total_selected: int
    high_risk: int
    avg_conflict_score: float
    avg_register_score: float
    summary_text: str
    overall_report: Optional[str] = None
    candidates: List[SimulationCandidateResult] = field(default_factory=list)


@pydantic_dataclass
class SimulationJobCreateResponse:
    job_id: str


@pydantic_dataclass
class SimulationJobStatusResponse:
    job_id: str
    status: str
    result: Optional[SimulationResponse] = None
    error: Optional[str] = None


@pydantic_dataclass
class SimulationConfigResponse:
    model_name: str
