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

_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")


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
        self._debug = _is_truthy(os.getenv("TRADEMARK_LLM_DEBUG"))

    def available(self) -> bool:
        return self._enabled

    def generate(self, text: str, limit: int = 10) -> List[str]:
        if not self._enabled:
            return []
        text = (text or "").strip()
        if not text:
            return []

        client = self._ensure_client()
        attempts = 0
        max_attempts = 6

        while attempts < max_attempts:
            variants: List[str] = []
            seen: set[str] = set()
            try:
                prompt = self._build_prompt(text, limit - len(variants))
                self._debug_print("prompt", prompt)
                response = client.responses.create(
                    model=self._model_id,
                    temperature=self._temperature,
                    max_output_tokens=512,
                    input=prompt,
                )
                self._log_usage(response)
            except OpenAIError as exc:
                attempts += 1
                if attempts >= max_attempts:
                    raise RuntimeError(
                        f"LLM trademark variant generation failed for '{text}'."
                    ) from exc
                continue

            content = (response.output_text or "").strip()
            if not content:
                content = self._first_text(response)
            self._debug_print("raw_output", content)
            parsed = self._parse_json_candidates(content or "")
            rows = parsed if parsed else _split_variants(content or "")
            for entry in rows:
                key = entry.lower()
                if not entry or key == text.lower() or key in seen:
                    continue
                variants.append(entry)
                seen.add(key)
                if len(variants) >= limit:
                    break

            latin, hangul = self._split_languages(variants)
            if not latin or not hangul:
                attempts += 1
                continue

            return self._mix_languages(latin, hangul, limit)

        raise RuntimeError(
            f"LLM trademark variant generation failed for '{text}' (language diversity)."
        )

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
            "당신은 한국 상표 심사 기준을 잘 아는 전문 심사관이다. "
            "거래 사회의 일반 수요자가 상표의 외관·호칭·관념 중 어느 하나라도 혼동할 "
            "가능성이 있으면 유사하다고 판단한다. 여러 음절로 이뤄진 표장에서는 첫 음절"
            "(어두)이 특히 중요하고, 로마자 표기는 한국인이 자연스럽게 영어식으로 읽는"
            "방식과 한글 병기 형태를 모두 고려한다. 한자나 의미형 표장에서는 관념적 연상도"
            "중요하다. 이러한 원칙을 지켜 사용자 입력과 혼동될 수 있는 후보를 제안하라."
        )

        user_prompt = (
            "상표명: "
            + text
            + "\n출력 형식: 설명 없이 JSON 배열 하나만 반환하고 반드시 "
            + str(limit)
            + "개의 고유 문자열을 넣는다. 지침:"
            " 1) 영어 또는 한글만 사용한다."
            " 2) 발음이 헷갈리게 들리거나 첫 음절이 동일/유사한 변형을 우선 생성한다"
            "(모음/자음 치환, 장·단음 변형, 하이픈·공백 조정, 반복, 영어-한글 음역 교차 포함)."
            " 3) 의미나 관념이 비슷한 조합은 상표 길이를 크게 바꾸지 않는 범위에서만 허용하며"
            " 일반 수요자가 직관적으로 떠올릴 수 있는 단어만 사용한다."
            " 4) 'PRO', 'MAX', '360'처럼 기능성·등급을 강조하는 흔한 접미사나 임의의 대문자·숫자를 덧붙이는 방식은 모두 금지한다 (규칙만 따르고 예시를 그대로 복사하지 말 것)."
            " 5) 대신 철자 치환, 하이픈/공백 이동, 일부 음소 삭제, 대소문자/강조, 반복 문자 등 실제 사용자가 착각할 만한 음운적 변형을 다양하게 시도한다."
            " 6) 영어식 표기와 한글 음역 표기가 번갈아가며 배열되도록 순서를 구성한다."
            " 7) 무의미한 숫자 나열, 괄호·설명 문구는 금지."
            " 8) 각 항목은 25자 이하이며 앞뒤 공백을 제거한다."
            " 9) 원문과 완전히 동일한 표기는 출력하지 않는다."
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

    def _split_languages(self, variants: List[str]) -> tuple[List[str], List[str]]:
        latin: List[str] = []
        hangul: List[str] = []
        for variant in variants:
            has_hangul = bool(_HANGUL_RE.search(variant))
            has_latin = bool(_LATIN_RE.search(variant))
            if has_hangul:
                hangul.append(variant)
            if has_latin:
                latin.append(variant)
        return latin, hangul

    def _mix_languages(
        self, latin: List[str], hangul: List[str], limit: int
    ) -> List[str]:
        result: List[str] = []
        idx_lat = idx_han = 0
        while len(result) < limit and (idx_lat < len(latin) or idx_han < len(hangul)):
            if idx_lat < len(latin):
                result.append(latin[idx_lat])
                idx_lat += 1
            if len(result) < limit and idx_han < len(hangul):
                result.append(hangul[idx_han])
                idx_han += 1

        remainder = latin[idx_lat:] + hangul[idx_han:]
        for item in remainder:
            if len(result) >= limit:
                break
            result.append(item)
        return result[:limit]

    def _debug_print(self, label: str, payload) -> None:
        if not self._debug:
            return
        try:
            printable = payload
            if isinstance(payload, list) or isinstance(payload, dict):
                printable = json.dumps(payload, ensure_ascii=False, indent=2)
            print(f"[LLM_SYNONYM_DEBUG] {label}: {printable}")
        except Exception:
            print(f"[LLM_SYNONYM_DEBUG] {label}: {payload}")




@lru_cache(maxsize=1)
def get_llm_service() -> TrademarkLLMSynonymService:
    return TrademarkLLMSynonymService()
