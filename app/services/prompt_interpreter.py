"""LLM-backed interpreter for textual re-search prompts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from openai import OpenAI, OpenAIError

from app.services.synonym_service import _is_truthy  # reuse existing helper


@dataclass
class PromptInterpretation:
    """Structured instructions derived from a user prompt."""

    additional_terms: List[str] = field(default_factory=list)
    must_prefix: Optional[str] = None
    must_include: List[str] = field(default_factory=list)
    must_exclude: List[str] = field(default_factory=list)
    notes: Optional[str] = None
    fallback_reason: Optional[str] = None
    raw_response: Optional[str] = None

    @property
    def has_constraints(self) -> bool:
        return bool(
            (self.must_prefix and self.must_prefix.strip())
            or self.must_include
            or self.must_exclude
        )


class PromptInterpreter:
    """Interpret free-form prompts into structured search hints."""

    def __init__(self) -> None:
        self._enabled = _is_truthy(os.getenv("TRADEMARK_LLM_ENABLED"))
        self._model_id = os.getenv("PROMPT_LLM_MODEL", os.getenv("TRADEMARK_LLM_MODEL", "gpt-4o-mini"))
        self._temperature = float(os.getenv("PROMPT_LLM_TEMPERATURE", "0.1"))
        self._api_key = os.getenv("OPENAI_API_KEY")
        if not self._api_key:
            self._enabled = False
        self._client: OpenAI | None = None

    def interpret(self, base_text: str, prompt: str) -> PromptInterpretation:
        prompt = (prompt or "").strip()
        if not prompt:
            return PromptInterpretation()

        if not self._enabled:
            return self._fallback(prompt, "llm_disabled")

        try:
            client = self._ensure_client()
            system_prompt = (
                "You are an expert trademark search assistant. "
                "Summarize the user's clarification into structured constraints."
            )
            user_prompt = (
                "Return strict JSON with keys: additional_terms (array of up to 5 short phrases), "
                "must_prefix (string or null), must_include (array of short lowercase tokens), "
                "must_exclude (array of tokens), notes (string or null). "
                "Do not add commentary."
                f"\nBase trademark query: {base_text or '(none)'}"
                f"\nUser clarification: {prompt}"
            )
            response = client.responses.create(
                model=self._model_id,
                temperature=self._temperature,
                max_output_tokens=400,
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                ],
            )
            raw_text = response.output_text or self._first_text(response)
            data = self._parse_json_block(raw_text)
            if not isinstance(data, dict):
                return self._fallback(prompt, "non_json_response", raw_text)
            interpretation = PromptInterpretation(
                additional_terms=self._sanitize_terms(data.get("additional_terms", [])),
                must_prefix=self._clean_str(data.get("must_prefix")),
                must_include=self._sanitize_terms(data.get("must_include", [])),
                must_exclude=self._sanitize_terms(data.get("must_exclude", [])),
                notes=self._clean_str(data.get("notes")),
                raw_response=raw_text,
            )
            self._augment_from_prompt(prompt, interpretation)
            return interpretation
        except OpenAIError as exc:  # pragma: no cover - network/LLM failures
            return self._fallback(prompt, f"llm_error:{exc.__class__.__name__}")
        except Exception:  # pragma: no cover - safety net
            return self._fallback(prompt, "llm_parse_error")

    def _ensure_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def _fallback(self, prompt: str, reason: str, raw: Optional[str] = None) -> PromptInterpretation:
        interpretation = PromptInterpretation(
            additional_terms=self._sanitize_terms([prompt]),
            fallback_reason=reason,
            raw_response=raw,
        )
        self._augment_from_prompt(prompt, interpretation)
        return interpretation

    def _sanitize_terms(self, values: List[str]) -> List[str]:
        terms: List[str] = []
        for value in values:
            cleaned = self._clean_str(value)
            if cleaned:
                terms.append(cleaned)
        return terms[:5]

    def _clean_str(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    def _augment_from_prompt(self, prompt: str, interpretation: PromptInterpretation) -> None:
        prompt_lower = prompt.lower()
        prefix_match = re.search(r"'([^']+)'\s*로\s*시작", prompt_lower)
        if prefix_match and not interpretation.must_prefix:
            interpretation.must_prefix = prefix_match.group(1)
        if "로 시작" in prompt_lower and "t-" in prompt_lower and not interpretation.must_prefix:
            interpretation.must_prefix = "t-"

    def _parse_json_block(self, raw_text: Optional[str]) -> object:
        if not raw_text:
            raise ValueError("Empty response")
        snippet = raw_text.strip()
        if "```" in snippet:
            parts = snippet.split("```")
            for chunk in parts:
                chunk = chunk.strip()
                if chunk.lower().startswith("json"):
                    snippet = chunk[4:].strip()
                    break
        return json.loads(snippet)

    @staticmethod
    def _first_text(response) -> str:  # type: ignore[no-untyped-def]
        for item in getattr(response, "output", []) or []:
            if item.type == "message":
                for content in item.content or []:
                    if content.get("type") in {"text", "output_text", "input_text"}:
                        return str(content.get("text", ""))
        return ""
