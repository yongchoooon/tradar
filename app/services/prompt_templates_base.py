"""Shared types for LangGraph prompt templates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PromptBundle:
    lang: str
    final_reporter: str
    examiner: str
    applicant: str
    examiner_reply: str
    reporter: str
    scorer: str
    restriction_suffix: str
    system_message_template: str
    case_label: str
    conversation_label: str
    conversation_empty: str
    instruction_label: str
    quant_label: str
    copy_from_block: str
    metrics_labels: Dict[str, str]
    roles: Dict[str, str]
