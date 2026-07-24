"""HTTP layer: routing, validation, rate limiting, response shaping (ROADMAP §2–§3).

Checks are ordered cheapest-first: parse → validate → rate-limit → model call.
This layer knows nothing about how answers are generated; it talks to the
ModelRouter and returns JSON.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse

from linbot.model.base import ProviderError
from linbot.model.prompts import SYSTEM_PROMPT_VERSION
from linbot.server.chat_page import CHAT_PAGE
from linbot.server.schemas import AskRequest, AskResponse
from linbot.storage.log import log_request

router = APIRouter()


MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_MESSAGE_CHARS = 8000


def _sanitize_history(history) -> list[dict[str, str]]:
    """Client-supplied history is untrusted input: bound its size and keep the
    shape model APIs require (first message must be from the user)."""
    trimmed = [
        {"role": m.role, "content": m.content[:MAX_HISTORY_MESSAGE_CHARS]}
        for m in history[-MAX_HISTORY_MESSAGES:]
    ]
    while trimmed and trimmed[0]["role"] != "user":
        trimmed.pop(0)
    return trimmed


def _client_id(request: Request) -> str:
    # Behind a PaaS proxy the real caller is in X-Forwarded-For; direct
    # connections fall back to the socket address.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def chat() -> str:
    return CHAT_PAGE


@router.post("/ask", response_model=AskResponse)
async def ask(payload: AskRequest, request: Request, background: BackgroundTasks) -> AskResponse:
    state = request.app.state
    question = payload.question.strip()

    if not question:
        raise HTTPException(
            status_code=400, detail="question is required and must be a non-empty string"
        )
    if len(question) > state.settings.max_question_chars:
        raise HTTPException(
            status_code=400,
            detail=f"question is too long (max {state.settings.max_question_chars} characters)",
        )

    client_id = _client_id(request)
    if not state.limiter.allow(client_id):
        raise HTTPException(status_code=429, detail="rate limit exceeded, try again shortly")

    # Conversation history rides in from the client and goes straight to the
    # model call — it is never stored, so a page refresh resets the session.
    history = _sanitize_history(payload.history)

    # Retrieval (RAG): ground the answer in site content when a retriever is
    # configured. Retrieval failures degrade to an un-grounded answer.
    context: list[str] | None = None
    retrieved_sources: str | None = None
    if state.retriever is not None:
        retrieved = await state.retriever.retrieve(question)
        if retrieved:
            context = [r.as_context() for r in retrieved]
            retrieved_sources = json.dumps([r.source_url for r in retrieved])

    try:
        answer = await state.model_router.answer(question, context, history)
    except ProviderError as exc:
        # Log the failure too — error rows are part of the operational record —
        # but return a clean 502, never a stack trace (ROADMAP §3). Logged
        # inline (not via BackgroundTasks) because background tasks only run
        # when attached to a returned response, and this path raises instead.
        await log_request(
            state.session_factory,
            question=question,
            client_id=client_id,
            system_prompt_version=SYSTEM_PROMPT_VERSION,
            error=str(exc),
        )
        raise HTTPException(status_code=502, detail="the model service is unavailable") from exc

    # Fire-and-forget after the response: the student never waits on the insert.
    background.add_task(
        log_request,
        state.session_factory,
        question=question,
        answer=answer.text,
        model_id=answer.model_id,
        provider=answer.provider,
        latency_ms=answer.latency_ms,
        fallback_used=answer.fallback_used,
        client_id=client_id,
        system_prompt_version=SYSTEM_PROMPT_VERSION,
        retrieved_sources=retrieved_sources,
    )
    return AskResponse(answer=answer.text)
