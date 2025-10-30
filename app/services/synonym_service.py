"""LLM-based trademark synonym generator using OpenAI GPT models."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List

from openai import OpenAI, OpenAIError


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.lower() in {"1", "true", "yes", "on"}


def _sanitize(entry: str) -> str:
    entry = entry.strip()
    entry = re.sub(r"^[0-9]+[).:-]\s*", "", entry)
    entry = entry.strip("-•*· ")
    return entry.strip()


def _split_variants(text: str) -> Iterable[str]:
    for line in text.splitlines():
        cleaned = _sanitize(line)
        if not cleaned:
            continue
        if len(cleaned) > 120:
            continue
        yield cleaned


class TrademarkLLMSynonymService:
    """Wraps a Hugging Face chat model to propose similar trademark names.

    The service is opt-in via the ``TRADEMARK_LLM_ENABLED`` environment variable so
    that local development and automated tests do not attempt to download large
    models by default. When enabled, the model id can be configured with
    ``TRADEMARK_LLM_MODEL`` (defaults to ``gpt-4o-mini``).
    """

    def __init__(self) -> None:
        self._enabled = _is_truthy(os.getenv("TRADEMARK_LLM_ENABLED"))
        self._model_id = os.getenv("TRADEMARK_LLM_MODEL", "gpt-4o-mini")
        self._reasoning_level = os.getenv("TRADEMARK_LLM_REASONING", "medium")
        self._temperature = float(os.getenv("TRADEMARK_LLM_TEMPERATURE", "0.2"))
        self._client: OpenAI | None = None
        self._api_key = os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            self._enabled = False
        self._usage_log_path = self._ensure_usage_log()

    def available(self) -> bool:
        return self._enabled

    def generate(self, text: str, limit: int = 10) -> List[str]:
        if not self._enabled:
            return []
        text = (text or "").strip()
        if not text:
            return []

        try:
            client = self._ensure_client()
            prompt = self._build_prompt(text, limit)
            response = client.responses.create(
                model=self._model_id,
                temperature=self._temperature,
                max_output_tokens=512,
                input=prompt,
            )
            self._log_usage(response)
        except OpenAIError as exc:
            raise RuntimeError(
                f"LLM trademark variant generation failed for '{text}'."
            ) from exc

        response_text = (response.output_text or "").strip()
        content = response_text if response_text else self._first_text(response)
        content = content or ""
        parsed = self._parse_json_candidates(content)
        rows = parsed if parsed else _split_variants(content)
        variants = []
        seen = set()
        for entry in rows:
            key = entry.lower()
            if key == text.lower() or key in seen:
                continue
            variants.append(entry)
            seen.add(key)
            if len(variants) >= limit:
                break
        return variants

    def _ensure_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _ensure_usage_log(self) -> Path:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / "openai_usage.csv"
        if not path.exists():
            path.write_text("timestamp,model,input_tokens,output_tokens,total_tokens,input_cost_usd,output_cost_usd,total_cost_usd\n", encoding="utf-8")
        return path

    def _log_usage(self, response) -> None:  # type: ignore[no-untyped-def]
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "input_tokens", None)
        output_tokens = getattr(usage, "output_tokens", None)
        total_tokens = getattr(usage, "total_tokens", None)
        if input_tokens is None and output_tokens is None and total_tokens is None:
            return

        # OpenAI pricing for gpt-4o-mini: $0.15 per 1M input, $0.60 per 1M output
        in_rate = float(os.getenv("OPENAI_RATE_INPUT_USD_PER_MTOKEN", "0.15"))
        out_rate = float(os.getenv("OPENAI_RATE_OUTPUT_USD_PER_MTOKEN", "0.60"))
        input_cost = (input_tokens or 0) * (in_rate / 1_000_000)
        output_cost = (output_tokens or 0) * (out_rate / 1_000_000)
        total_cost = input_cost + output_cost

        created = getattr(response, "created_at", None)
        if created is None:
            created = getattr(response, "created", None)
        if isinstance(created, (int, float)):
            created = datetime.utcfromtimestamp(created)
        timestamp = created.isoformat() if hasattr(created, "isoformat") else ""

        line = (
            f"{timestamp},"
            f"{self._model_id},"
            f"{input_tokens if input_tokens is not None else ''},"
            f"{output_tokens if output_tokens is not None else ''},"
            f"{total_tokens if total_tokens is not None else ''},"
            f"{input_cost:.10f},"
            f"{output_cost:.10f},"
            f"{total_cost:.10f}\n"
        )
        with self._usage_log_path.open("a", encoding="utf-8") as fh:
            fh.write(line)

    def _build_prompt(self, text: str, limit: int) -> list[dict]:
        system_prompt = (
            "You are an expert in global trademark examination."
            " Generate candidate marks that a human might judge confusingly"
            " similar to the user's mark while staying within Korean Hangul"
            " and English scripts."
        )

        user_prompt = (
            "Trademark name: "
            + text
            + "\nReturn a JSON array (no prose) with up to "
            + str(limit)
            + " unique strings."
            " Rules:"
            " 1) Only output variants written in English (Latin letters) or Korean Hangul."
            " 2) Avoid adding parenthetical language labels or explanatory text."
            " 3) Provide meaningful phonetic or semantic tweaks (case changes, repeated letters,"
            " consonant swaps, spacing, Hangul transliterations)."
            " 4) Do not output entries that merely add or remove a single character from the original."
            " 5) Keep each variant <= 25 characters and trim whitespace."
            " 6) Do not repeat the exact original spelling."
        )
        return [
            {
                "role": "system",
                "content": [
                    {"type": "input_text", "text": system_prompt},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": user_prompt},
                ],
            },
        ]

    @staticmethod
    def _first_text(response) -> str:
        for item in getattr(response, "output", []) or []:
            if item.type == "message":
                for content in item.content or []:
                    if content.get("type") in {"text", "output_text", "input_text"}:
                        return str(content.get("text", ""))
        return ""

    @staticmethod
    def _parse_json_candidates(raw: str) -> list[str]:
        snippet = raw
        if "```" in raw:
            parts = raw.split("```")
            for chunk in parts:
                chunk = chunk.strip()
                if chunk.lower().startswith("json"):
                    snippet = chunk[4:].strip()
                    break
        try:
            data = json.loads(snippet)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
        return []


@lru_cache(maxsize=1)
def get_llm_service() -> TrademarkLLMSynonymService:
    return TrademarkLLMSynonymService()
