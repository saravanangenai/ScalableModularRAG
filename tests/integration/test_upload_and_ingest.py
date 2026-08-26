"""Requires real Postgres, MinIO, Keycloak, Qdrant, and Memurai, plus a running Celery
worker (`uv run celery -A workers.celery_app worker --pool=solo`) and a real
OPENAI_API_KEY — see plan.md's "Config additions" callout. See test_auth_flow.py for the
Keycloak-specific requirements this also relies on."""

import asyncio
import time
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models

from packages.ingestion import Settings as IngestionSettings

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "sample.pdf"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_tenant_and_workspace(api_client, token: str) -> tuple[str, str]:
    tenant_response = await api_client.post(
        "/tenants",
        json={"name": "Ingestion Tenant", "slug": f"ingest-{uuid.uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    tenant_id = tenant_response.json()["id"]
    workspace_response = await api_client.post(
        f"/tenants/{tenant_id}/workspaces", json={"name": "Default"}, headers=_auth(token)
    )
    workspace_id = workspace_response.json()["id"]
    return tenant_id, workspace_id


async def _poll_job_until_terminal(
    api_client, token: str, workspace_id: str, job_id: str, timeout: float = 600, interval: float = 3
) -> dict:
    # 600s, not the ~90s a real run normally takes: real end-to-end parsing (PyMuPDF +
    # Tesseract writing many small temp image files) has been observed to occasionally
    # stall for 10+ minutes on this Windows dev box, most likely real-time antivirus
    # scanning those temp files — an environment quirk, not a pipeline bug (see plan.md's
    # Implementation findings).
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = await api_client.get(
            f"/workspaces/{workspace_id}/jobs/{job_id}", headers=_auth(token)
        )
        body = response.json()
        if body["status"] in ("ready", "failed"):
            return body
        await asyncio.sleep(interval)
    raise TimeoutError(f"job {job_id} did not reach a terminal state within {timeout}s")


async def test_upload_ingests_and_reaches_ready(api_client, user1_token):
    tenant_id, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    pdf_bytes = FIXTURE_PDF.read_bytes()
    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        headers=_auth(user1_token),
    )
    assert upload_response.status_code == 202
    body = upload_response.json()
    assert body["status"] == "queued"
    document_id = body["document_id"]
    job_id = body["job_id"]

    job = await _poll_job_until_terminal(api_client, user1_token, workspace_id, job_id)
    assert job["status"] == "ready", job.get("failure_reason")

    doc_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents/{document_id}", headers=_auth(user1_token)
    )
    doc_body = doc_response.json()
    assert doc_body["status"] == "ready"
    assert doc_body["current_version_id"] is not None

    settings = IngestionSettings()
    qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    points, _ = qdrant_client.scroll(
        collection_name=settings.qdrant_collection_name,
        scroll_filter=models.Filter(
            must=[models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))]
        ),
        limit=50,
    )
    assert len(points) > 0
    payload = points[0].payload
    assert payload["tenant_id"] == tenant_id
    assert payload["workspace_id"] == workspace_id
    assert payload["document_id"] == document_id
    assert payload["is_current_version"] is True
