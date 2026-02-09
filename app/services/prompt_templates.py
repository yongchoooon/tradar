"""Prompt bundle selector for LangGraph agents."""

from __future__ import annotations

from app.services.prompt_templates_base import PromptBundle
from app.services.prompt_templates_ko import BUNDLE as KO_BUNDLE
from app.services.prompt_templates_en import BUNDLE as EN_BUNDLE


def get_prompt_bundle(language: str | None) -> PromptBundle:
    if language and str(language).lower().startswith("en"):
        return EN_BUNDLE
    return KO_BUNDLE
