"""Schemas for AI agent simulation requests/responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from app.schemas.search import ImageRefPayload

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
    image_path: Optional[str] = None
    thumb_url: Optional[str] = None
    goods_services: Optional[str] = None


@pydantic_dataclass
class SimulationSelectionRef:
    application_number: str
    variant: VariantType


@pydantic_dataclass
class SimulationRequest:
    search_id: Optional[str] = None
    selection_refs: List[SimulationSelectionRef] = field(default_factory=list)
    selections: List[SimulationSelection] = field(default_factory=list)
    debug: bool = False
    query_title: Optional[str] = None
    user_goods_classes: List[str] = field(default_factory=list)
    user_group_codes: List[str] = field(default_factory=list)
    user_goods_names: List[str] = field(default_factory=list)
    user_image_b64: Optional[str] = None
    user_image_mime: Optional[str] = None
    user_image_ref: Optional[ImageRefPayload] = None


@pydantic_dataclass
class SimulationCandidateResult:
    application_number: str
    title: str
    variant: VariantType
    conflict_score: float
    register_score: float
    status: Optional[str]
    class_codes: List[str]
    thumb_url: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    agent_summary: Optional[str] = None
    agent_risk: Optional[str] = None
    transcript: List[str] = field(default_factory=list)
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
    max_conflict_score: float = 0.0
    min_register_score: float = 0.0
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
