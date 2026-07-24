"""Request/response shapes for the HTTP layer (ROADMAP §2)."""

from __future__ import annotations

from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


class ErrorResponse(BaseModel):
    error: str
