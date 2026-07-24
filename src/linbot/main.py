"""App factory: wires config → providers → router → storage → HTTP.

Run with:  uvicorn linbot.main:create_app --factory
The factory pattern (instead of a module-level `app`) is what lets tests build
an app with their own Settings and fake providers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

from linbot.config import Settings, load_settings
from linbot.model.base import Provider
from linbot.model.providers.fake import FakeProvider
from linbot.model.router import ModelRouter
from linbot.server.routes import router as api_router
from linbot.storage.db import create_engine, create_session_factory


def _build_provider(name: str, settings: Settings, cache: dict[str, Provider]) -> Provider:
    if name not in cache:
        if name == "fake":
            cache[name] = FakeProvider()
        elif name == "deepseek":
            from linbot.model.providers.deepseek import build_deepseek_provider

            cache[name] = build_deepseek_provider(settings)
        elif name == "hf":
            from linbot.model.providers.hf_endpoint import build_hf_provider

            cache[name] = build_hf_provider(settings)
        else:  # unreachable: config validates provider names
            raise ValueError(f"unknown provider {name!r}")
    return cache[name]


def build_model_router(settings: Settings) -> ModelRouter:
    cache: dict[str, Provider] = {}
    primary = _build_provider(settings.provider, settings, cache)
    candidate = (
        _build_provider(settings.canary_provider, settings, cache)
        if settings.canary_provider
        else None
    )
    fallback = (
        _build_provider(settings.fallback_provider, settings, cache)
        if settings.fallback_provider
        else None
    )
    return ModelRouter(
        primary=primary,
        candidate=candidate,
        canary_percent=settings.canary_percent,
        fallback=fallback,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine = create_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await engine.dispose()

    app = FastAPI(title="LinBot", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.model_router = build_model_router(settings)

    from linbot.server.ratelimit import SlidingWindowLimiter

    app.state.limiter = SlidingWindowLimiter(
        limit=settings.rate_limit, window_seconds=settings.rate_limit_window_seconds
    )

    # The roadmap's error contract (§2) uses {"error": ...} bodies and 400 for
    # bad input; FastAPI defaults to {"detail": ...} and 422, so both are mapped.
    @app.exception_handler(RequestValidationError)
    async def on_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "question is required and must be a non-empty string"},
        )

    @app.exception_handler(HTTPException)
    async def on_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    app.include_router(api_router)
    return app
