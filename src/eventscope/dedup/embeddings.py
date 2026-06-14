"""Text embeddings for dedup.

Providers:
  * ``stub`` — offline, deterministic bag-of-words hashing vector. No heavy
               dependency; sufficient to cluster near-duplicate titles in tests
               and local dev.
  * ``sentence-transformers`` — real semantic embeddings (docx's choice), used
               when the optional extra is installed and configured.
"""
from __future__ import annotations

import abc
import hashlib
import math
import re

from ..config import get_settings

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_DIM = 256


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class Embedder(abc.ABC):
    @abc.abstractmethod
    def embed(self, text: str) -> list[float]:
        ...


class StubEmbedder(Embedder):
    """Hashing bag-of-words into a fixed-dim vector. Deterministic & offline."""

    dim = _DIM

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall((text or "").lower())
        for tok in tokens:
            h = int.from_bytes(hashlib.md5(tok.encode("utf-8")).digest()[:4], "big")
            vec[h % self.dim] += 1.0
        return vec


class SentenceTransformerEmbedder(Embedder):  # pragma: no cover - optional dep
    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, text: str) -> list[float]:
        return self._model.encode(text or "").tolist()


def get_embedder() -> Embedder:
    provider = (get_settings().embedding_provider or "stub").lower()
    if provider in ("sentence-transformers", "st"):  # pragma: no cover - optional dep
        try:
            return SentenceTransformerEmbedder()
        except Exception:
            return StubEmbedder()
    return StubEmbedder()
