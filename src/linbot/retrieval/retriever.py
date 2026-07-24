"""Query-time retrieval: embed the question, rank stored chunks by cosine
similarity, return the best few as prompt context."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from linbot.retrieval.embedder import RetrievalError, cosine_similarity
from linbot.storage.models import Chunk

logger = logging.getLogger("linbot.retrieval")


@dataclass
class RetrievedChunk:
    source_url: str
    heading: str | None
    content: str
    similarity: float

    def as_context(self) -> str:
        header = f"[source: {self.source_url}" + (f" — {self.heading}]" if self.heading else "]")
        return f"{header}\n{self.content}"


class Retriever:
    def __init__(
        self,
        embedder,
        session_factory: async_sessionmaker,
        top_k: int = 4,
        min_similarity: float = 0.3,
    ) -> None:
        self._embedder = embedder
        self._session_factory = session_factory
        self.top_k = top_k
        self.min_similarity = min_similarity

    async def retrieve(self, question: str) -> list[RetrievedChunk]:
        """Best-effort: retrieval problems degrade to an un-grounded answer,
        never to a failed request."""
        try:
            [query_embedding] = await self._embedder.embed([question], input_type="query")
        except RetrievalError:
            logger.exception("query embedding failed; answering without context")
            return []

        async with self._session_factory() as session:
            chunks = (await session.execute(select(Chunk))).scalars().all()

        scored = [
            RetrievedChunk(
                source_url=c.source_url,
                heading=c.heading,
                content=c.content,
                similarity=cosine_similarity(query_embedding, json.loads(c.embedding)),
            )
            for c in chunks
        ]
        scored.sort(key=lambda r: r.similarity, reverse=True)
        return [r for r in scored[: self.top_k] if r.similarity >= self.min_similarity]
