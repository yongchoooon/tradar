"""Placeholder text variant generator mimicking LLM-based synonym expansion."""

from __future__ import annotations

import re
from typing import List, Set

from app.services.synonym_service import get_llm_service


class TextVariantService:
    """Generates lightweight variants of a trademark name.

    In production this should call an LLM to create phonetic, semantic, and
    multilingual variants. Here we approximate the behaviour deterministically
    so that the search pipeline can be tested without external dependencies.
    """

    _ALLOWED_PATTERN = re.compile(r"^[0-9A-Za-z가-힣\-\s'·]+$")

    def __init__(self) -> None:
        self._llm = get_llm_service()

    def generate(self, text: str) -> List[str]:
        text = (text or "").strip()
        if not text:
            return []

        collapsed = re.sub(r"\s+", " ", text).strip()
        alnum = re.sub(r"[^0-9A-Za-z가-힣]+", " ", text).strip()
        no_space = collapsed.replace(" ", "")

        variants: List[str] = []
        seen: Set[str] = set()

        def _add(candidate: str) -> None:
            candidate = (candidate or "").strip()
            if not candidate:
                return
            if candidate == text:
                return
            if not self._accept_candidate(text, candidate):
                return
            key = candidate.lower()
            if key in seen:
                return
            seen.add(key)
            variants.append(candidate)

        seeds = [
            text.lower(),
            text.upper(),
            text.title(),
            collapsed,
            alnum if alnum and alnum != collapsed else "",
            no_space if no_space and no_space != collapsed else "",
        ]
        for seed in seeds:
            _add(seed)

        if self._llm.available():
            for cand in self._llm.generate(text, limit=10):
                _add(cand)

        return variants

    @classmethod
    def _accept_candidate(cls, base: str, candidate: str) -> bool:
        if "(" in candidate or ")" in candidate:
            return False
        if not cls._ALLOWED_PATTERN.match(candidate):
            return False

        base_norm = cls._normalize(base)
        cand_norm = cls._normalize(candidate)
        if not cand_norm or cand_norm == base_norm:
            return False

        return True

    @classmethod
    def _normalize(cls, text: str) -> str:
        return text.strip().lower()
