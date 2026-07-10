"""Shared helpers for trademark title display and prompt values."""

from __future__ import annotations

from typing import Optional


MISSING_MARK_TITLE_LABEL_KO = "(상표명 없음)"
MISSING_MARK_TITLE_LABEL_EN = "(No name)"

_MISSING_MARK_TITLE_LABELS = {
    MISSING_MARK_TITLE_LABEL_KO,
    MISSING_MARK_TITLE_LABEL_EN,
}


def normalize_mark_title(value: Optional[str]) -> str:
    """Return an actual mark title, or an empty string for placeholder labels."""
    text = (value or "").strip()
    if not text or text in _MISSING_MARK_TITLE_LABELS:
        return ""
    return text


def missing_mark_title_label(language: Optional[str]) -> str:
    if str(language or "").lower().startswith("en"):
        return MISSING_MARK_TITLE_LABEL_EN
    return MISSING_MARK_TITLE_LABEL_KO


def localized_mark_title(value: Optional[str], language: Optional[str]) -> str:
    return normalize_mark_title(value) or missing_mark_title_label(language)
