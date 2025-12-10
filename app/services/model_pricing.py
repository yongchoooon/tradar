"""Model pricing table for OpenAI usage logging."""

from __future__ import annotations

from typing import Dict

MODEL_PRICING: Dict[str, Dict[str, float]] = {
    "gpt-5.1": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.40},
    "gpt-5.1-chat-latest": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-chat-latest": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5.1-codex-max": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5.1-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-codex": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-pro": {"input": 15.0, "cached_input": 0.0, "output": 120.0},
    "gpt-4.1": {"input": 2.0, "cached_input": 0.5, "output": 8.0},
    "gpt-4.1-mini": {"input": 0.40, "cached_input": 0.10, "output": 1.60},
    "gpt-4.1-nano": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
    "gpt-4o": {"input": 2.50, "cached_input": 1.25, "output": 10.0},
    "gpt-4o-2024-05-13": {"input": 5.0, "cached_input": 0.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "cached_input": 0.075, "output": 0.60},
}

DEFAULT_PRICING = MODEL_PRICING["gpt-5-nano"]


def get_model_pricing(model_name: str | None) -> Dict[str, float]:
    """Return pricing info for the given model (USD per 1M tokens)."""

    if not model_name:
        return DEFAULT_PRICING
    key = model_name.strip().lower()
    pricing = MODEL_PRICING.get(key)
    if pricing is None:
        return DEFAULT_PRICING
    return pricing
