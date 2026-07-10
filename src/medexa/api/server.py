"""Medexa API application factory.

The app is assembled from small, bounded-context routers (sessions, live,
transcripts, documentation, billing, claims) plus an internal/back-compat
router. Cross-cutting concerns (CORS, per-request tracing) are applied here.

HIPAA posture:
  * Structured logs are PHI-redacted at the formatter (see ``logging_setup``).
  * Every response carries an ``X-Request-ID`` for auditable correlation.
  * Live state lives behind a repository interface (in-memory locally, DynamoDB
    with KMS + TTL in the cloud) so no PHI is written to disk by default.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from medexa.api.routers import (
    billing,
    claims,
    documentation,
    health,
    legacy,
    live,
    sessions,
    stream,
    timers,
    transcripts,
)
from medexa.config import settings
from medexa.logging_setup import configure_logging, get_logger, new_request_id


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    logger = get_logger("medexa.api")

    app = FastAPI(
        title="Medexa API",
        version="0.2.0",
        description="Real-time therapy session intelligence API",
    )

    # CORS: credentials cannot be combined with the "*" wildcard per the spec.
    allow_credentials = "*" not in settings.cors_allow_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _request_id_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        rid = new_request_id()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    # Frontend contract routers.
    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(timers.router)
    app.include_router(live.router)
    app.include_router(stream.router)
    app.include_router(transcripts.router)
    app.include_router(documentation.router)
    app.include_router(billing.router)
    app.include_router(claims.router)
    # Internal / back-compat (timers, NCCI alert actions, SSE, raw panel).
    app.include_router(legacy.router)

    from fastapi.responses import JSONResponse
    import traceback

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        tbl = traceback.format_exc()
        logger.error("Unhandled exception: " + str(exc) + "\n" + tbl)
        return JSONResponse(
            status_code=500,
            content={"error": str(exc), "traceback": tbl}
        )

    logger.info("app_initialized", extra={"extra_fields": {"providers": {
        "path_b_enabled": settings.path_b_enabled,
        "path_b_provider": settings.path_b_provider,
        "path_b_model": settings.path_b_model_id,
        "soap_generator": settings.soap_generator,
        "summary_generator": settings.summary_generator,
        "transcription_provider": settings.transcription_provider,
        "deepgram_model": settings.deepgram_model if settings.transcription_provider == "deepgram" else None,
    }}})
    return app


app = create_app()
