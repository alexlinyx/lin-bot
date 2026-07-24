"""HTTP layer: routing, validation, rate limiting, response shaping (ROADMAP §2–§3).

Checks are ordered cheapest-first: parse → validate → rate-limit → model call.
This layer knows nothing about how answers are generated; it talks to the
ModelRouter and returns JSON.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from linbot.model.base import ProviderError
from linbot.model.prompts import SYSTEM_PROMPT_VERSION
from linbot.server.schemas import AskRequest, AskResponse
from linbot.storage.log import log_request

router = APIRouter()


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

    try:
        answer = await state.model_router.answer(question)
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
    )
    return AskResponse(answer=answer.text)
