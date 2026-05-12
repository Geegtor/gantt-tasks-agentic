from __future__ import annotations

import hashlib
import logging
import math
import re
from typing import Protocol

from openai import AsyncOpenAI

from app.config import get_settings

log = logging.getLogger(__name__)

# HashBagEmbedder output size — used to pick stricter replay thresholds.
HASH_EMBEDDING_DIM = 256


class Embedder(Protocol):
    async def embed(self, text: str) -> list[float]: ...


class OpenAIEmbedder:
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.embedding_model or "text-embedding-3-small"
        self._client = AsyncOpenAI(api_key=s.openai_api_key or None)

    async def embed(self, text: str) -> list[float]:
        r = await self._client.embeddings.create(model=self._model, input=text)
        return list(r.data[0].embedding)


class HashBagEmbedder:
    """Deterministic pseudo-embedding when no API key (demo / tests)."""

    _DIM = HASH_EMBEDDING_DIM

    async def embed(self, text: str) -> list[float]:
        toks = re.findall(r"\w+", text.lower())
        vec = [0.0] * self._DIM
        for t in toks:
            h = int(hashlib.sha256(t.encode()).hexdigest(), 16)
            vec[h % self._DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def get_embedder() -> Embedder:
    s = get_settings()
    if (s.openai_api_key or "").strip():
        return OpenAIEmbedder()
    return HashBagEmbedder()


async def maybe_embed(text: str) -> list[float] | None:
    try:
        e = get_embedder()
        return await e.embed(text)
    except Exception as ex:
        log.warning("Embedding failed: %s", ex)
        return None
