from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from apps.api.routers import api_keys, documents, jobs, workspaces
from packages.db.session import get_async_sessionmaker
from packages.exceptions import AuthenticationError, AuthorizationError, MembershipNotFoundError


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.session_factory = get_async_sessionmaker()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="mm-rag-api", lifespan=lifespan)

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

    app.include_router(workspaces.router)
    app.include_router(api_keys.router)
    app.include_router(documents.router)
    app.include_router(jobs.router)

    return app


app = create_app()
