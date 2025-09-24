"""Utility helpers for deterministic toy embeddings.

These hashed embeddings are *not* meant to be production ready. They create a
low-dimensional vector space from arbitrary tokens to let the pipeline run
without external ML dependencies.  Both query encoders and the mock vector
store share this helper so their representations remain compatible.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)
DEFAULT_DIM = 16


def tokenize(text: str) -> List[str]:
    """Split ``text`` into lowercase word tokens."""
    return [tok.lower() for tok in _TOKEN_RE.findall(text)]


def token_hash_index(token: str, dim: int = DEFAULT_DIM) -> int:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return digest[0] % dim


def normalize_accumulator(accum: Iterable[float]) -> List[float]:
    values = list(accum)
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def hashed_embedding(tokens: Iterable[str], dim: int = DEFAULT_DIM) -> List[float]:
    """Project tokens into a deterministic unit-length vector."""
    accum = [0.0] * dim
    for tok in tokens:
        accum[token_hash_index(tok, dim)] += 1.0
    return normalize_accumulator(accum)


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    """Cosine similarity for equally sized iterables."""
    num = sum(x * y for x, y in zip(a, b))
    denom_a = math.sqrt(sum(x * x for x in a))
    denom_b = math.sqrt(sum(y * y for y in b))
    denom = denom_a * denom_b
    if denom == 0:
        return 0.0
    return num / denom
