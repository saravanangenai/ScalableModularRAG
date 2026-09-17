from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from apps.api.config import Settings as ApiSettings
from apps.api.middleware.security_headers import SecurityHeadersMiddleware
from apps.api.routers import api_keys, audit, documents, jobs, search, workspaces
from packages.db.session import get_async_sessionmaker
from packages.exceptions import (
    AuthenticationError,
    AuthorizationError,
    MembershipNotFoundError,
    RateLimitExceededError,
)
from packages.observability import configure_sentry, configure_tracing
from packages.observability.config import Settings as ObservabilitySettings


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session_factory = get_async_sessionmaker()
    yield


def create_app() -> FastAPI:
    configure_tracing("mm-rag-api")
    observability_settings = ObservabilitySettings()
    configure_sentry(observability_settings.sentry_dsn, observability_settings.environment)

    api_settings = ApiSettings()

    app = FastAPI(title="mm-rag-api", lifespan=lifespan)
    # FastAPIInstrumentor must instrument before anything else touches app.middleware_stack
    # (Instrumentator().expose() below triggers an early build of it) — see
    # specs/061-observability-tracing-metrics/plan.md for the live-verified root cause.
    FastAPIInstrumentor.instrument_app(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=api_settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    Instrumentator().instrument(app).expose(app)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.exception_handler(AuthenticationError)
    async def _authentication_error_handler(request: Request, exc: AuthenticationError):
        return JSONResponse(status_code=401, content={"detail": "authentication failed"})

    @app.exception_handler(AuthorizationError)
    async def _authorization_error_handler(request: Request, exc: AuthorizationError):
        return JSONResponse(status_code=403, content={"detail": "forbidden"})

    @app.exception_handler(MembershipNotFoundError)
    async def _membership_not_found_handler(request: Request, exc: MembershipNotFoundError):
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @app.exception_handler(RateLimitExceededError)
    async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceededError):
        return JSONResponse(
            status_code=429,
            content={"detail": "rate limit exceeded"},
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    app.include_router(workspaces.router)
    app.include_router(api_keys.router)
    app.include_router(documents.router)
    app.include_router(jobs.router)
    app.include_router(search.router)
    app.include_router(audit.router)

    return app


app = create_app()
