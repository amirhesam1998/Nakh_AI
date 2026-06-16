"""
Embedding service for semantic recommendation re-ranking.

Stage-2 product scoring historically used naive Persian substring overlap,
which cannot tell that «سرمه‌ای» ≈ «آبی تیره» or «مجلسی» ≈ «رسمی». This module
adds an optional semantic layer using the Ollama embeddings endpoint (no new
heavy Python dependency — we already run Ollama for chat).

It is fully optional and defensive: if EMBEDDING_ENABLED is off or the embedder
is unreachable, callers fall back to token scoring. Embeddings are cached
in-process (queries repeat; the product catalogue is fairly stable).
"""
from __future__ import annotations

import logging
import math
import threading
from typing import List, Optional

import httpx

from app.config import settings
from app.services.metrics import metrics

logger = logging.getLogger(__name__)

# Small in-process LRU-ish cache (text -> vector). Bounded to avoid unbounded
# growth; fashion vocab is small so this hits often.
_CACHE_MAX = 4096
_cache: dict[str, List[float]] = {}
_cache_lock = threading.Lock()


class EmbeddingService:
    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "embedding_enabled", False))
        self._model = getattr(settings, "embedding_model", "nomic-embed-text")
        self._base_url = getattr(settings, "ollama_base_url", "http://localhost:11434").rstrip("/")
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=3.0, read=20.0, write=5.0, pool=5.0),
            )
        return self._client

    async def _embed_one(self, text: str) -> Optional[List[float]]:
        key = text.strip()
        if not key:
            return None
        with _cache_lock:
            cached = _cache.get(key)
        if cached is not None:
            return cached
        try:
            client = await self._get_client()
            resp = await client.post(
                "/api/embeddings", json={"model": self._model, "prompt": key}
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            if not isinstance(vec, list) or not vec:
                return None
            with _cache_lock:
                if len(_cache) >= _CACHE_MAX:
                    _cache.pop(next(iter(_cache)))  # evict oldest-ish
                _cache[key] = vec
            return vec
        except Exception as e:
            logger.warning("Embedding failed (%s: %s) — disabling for this call", type(e).__name__, e)
            return None

    async def embed(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embed a list of texts. Returns parallel list (None on failure)."""
        if not self._enabled:
            return [None] * len(texts)
        out: List[Optional[List[float]]] = []
        with metrics.timer("embedding.batch_seconds"):
            for t in texts:
                out.append(await self._embed_one(t))
        return out

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


def cosine(a: Optional[List[float]], b: Optional[List[float]]) -> float:
    """Cosine similarity mapped to [0, 1]; 0.0 when either vector is missing."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    sim = dot / (na * nb)
    # Cosine is in [-1, 1]; clamp & rescale to [0, 1] for blending with scores.
    return max(0.0, min(1.0, (sim + 1.0) / 2.0))


# Global instance
embedding_service = EmbeddingService()
