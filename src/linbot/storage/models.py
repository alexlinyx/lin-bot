"""Database schema.

The `requests` table is the project's most durable asset: it is simultaneously
the fine-tuning corpus and the evaluation ground truth (ROADMAP §9–§10), which
is why model attribution (`model_id`, `provider`, `fallback_used`) is recorded
on every row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    __tablename__ = "requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False)
    client_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    system_prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retrieved_sources: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list


class Chunk(Base):
    """A chunk of site content for retrieval (RAG).

    The embedding is stored as a JSON float array and similarity is computed
    in Python: the corpus is dozens of chunks, where a linear scan is faster
    than the operational cost of a vector extension. The Retriever interface
    hides this — growing into pgvector later is an internal swap.
    """

    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_url: Mapped[str] = mapped_column(String(500), index=True)
    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[str] = mapped_column(Text)  # JSON float array
