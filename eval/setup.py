import asyncio
import time
from pathlib import Path

import httpx
from httpx import ASGITransport

from eval.config import Settings
from packages.exceptions import EvalError


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def mint_token(settings: Settings) -> str:
    """Authenticates against the real local Keycloak (Resource Owner Password Credentials
    grant), same flow tests/integration/conftest.py::mint_token uses, same test-user
    credentials (specs/060-retrieval-evaluation/plan.md's Alternatives — no separate eval
    service account provisioned for this first increment)."""
    try:
        response = httpx.post(
            f"{settings.keycloak_issuer_url}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": settings.keycloak_test_client_id,
                "client_secret": settings.keycloak_test_client_secret,
                "username": settings.keycloak_test_username,
                "password": settings.keycloak_test_password,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()["access_token"]
    except Exception as exc:
        raise EvalError("failed to mint an eval auth token from Keycloak", original_exception=exc) from exc


def build_api_client() -> httpx.AsyncClient:
    """An in-process ASGI client against the real apps.api.main app — no separate uvicorn
    process needed, same pattern tests/integration/conftest.py::api_client uses. Sets
    app.state.session_factory directly rather than running the app's startup lifespan, since
    ASGITransport doesn't trigger it."""
    from apps.api.main import app
    from packages.db.session import get_async_sessionmaker

    app.state.session_factory = get_async_sessionmaker()
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://eval")


async def ensure_eval_workspace(api_client: httpx.AsyncClient, token: str, workspace_name: str) -> str:
    """Reuses an existing workspace named workspace_name if the eval user already belongs to
    one, else creates it — so eval doesn't spawn a fresh workspace (and re-ingest its fixture
    into it) on every run."""
    list_response = await api_client.get("/workspaces", headers=_auth(token))
    if list_response.status_code != 200:
        raise EvalError(f"failed to list workspaces: {list_response.status_code} {list_response.text}")

    for workspace in list_response.json():
        if workspace["name"] == workspace_name:
            return workspace["id"]

    create_response = await api_client.post(
        "/workspaces", json={"name": workspace_name}, headers=_auth(token)
    )
    if create_response.status_code != 201:
        raise EvalError(
            f"failed to create eval workspace: {create_response.status_code} {create_response.text}"
        )
    return create_response.json()["id"]


async def _poll_job_until_terminal(
    api_client: httpx.AsyncClient,
    token: str,
    workspace_id: str,
    job_id: str,
    timeout: float = 600,
    interval: float = 3,
) -> dict:
    # 600s: real end-to-end parsing has been observed to occasionally stall for 10+ minutes
    # on Windows dev boxes (antivirus scanning many small temp image files) — same note as
    # tests/integration/test_upload_and_ingest.py::_poll_job_until_terminal.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await api_client.get(
            f"/workspaces/{workspace_id}/jobs/{job_id}", headers=_auth(token)
        )
        body = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        await asyncio.sleep(interval)
    raise EvalError(f"eval fixture ingestion job {job_id} did not reach a terminal state within {timeout}s")


async def ensure_fixture_ingested(
    api_client: httpx.AsyncClient, token: str, workspace_id: str, fixture_path: str
) -> None:
    """Uploads the eval fixture — a no-op if it's already ingested, since 020's upload route
    is content-hash-deduped (UploadUnchanged response), which is what makes repeated eval
    runs cheap (specs/060-retrieval-evaluation/plan.md's Summary)."""
    path = Path(fixture_path)
    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": (path.name, path.read_bytes(), "application/pdf")},
        headers=_auth(token),
    )
    if upload_response.status_code not in (200, 202):
        raise EvalError(
            f"failed to upload eval fixture: {upload_response.status_code} {upload_response.text}"
        )

    body = upload_response.json()
    if body.get("status") == "unchanged":
        return

    job = await _poll_job_until_terminal(api_client, token, workspace_id, body["job_id"])
    if job["status"] != "ready":
        raise EvalError(f"eval fixture ingestion failed: {job.get('failure_reason')}")
