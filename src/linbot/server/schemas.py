"""Request/response shapes for the HTTP layer (ROADMAP §2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: str
    # Prior turns of the conversation, supplied by the client per request.
    # The server is stateless: this is the only place history exists, so a
    # page refresh genuinely resets the conversation.
    history: list[ChatMessage] = []


class AskResponse(BaseModel):
    answer: str


class ErrorResponse(BaseModel):
    error: str
