"""Requires the same live stack as test_upload_and_ingest.py (Postgres, MinIO, Keycloak,
Qdrant, Memurai, a running Celery worker, and a real OPENAI_API_KEY)."""

import uuid
from pathlib import Path

from tests.integration.test_upload_and_ingest import (
    _auth,
    _create_tenant_and_workspace,
    _poll_job_until_terminal,
)

FIXTURE_PDF = Path(__file__).resolve().parents[1] / "fixtures" / "sample.pdf"


async def test_reuploading_identical_bytes_is_a_no_op(api_client, user1_token):
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)
    pdf_bytes = FIXTURE_PDF.read_bytes()

    first_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("versioned.pdf", pdf_bytes, "application/pdf")},
        headers=_auth(user1_token),
    )
    assert first_response.status_code == 202
    first_body = first_response.json()

    job = await _poll_job_until_terminal(
        api_client, user1_token, workspace_id, first_body["job_id"]
    )
    assert job["status"] == "ready", job.get("failure_reason")

    versions_before = await api_client.get(
        f"/workspaces/{workspace_id}/documents/{first_body['document_id']}/versions",
        headers=_auth(user1_token),
    )
    version_count_before = len(versions_before.json())

    second_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("versioned.pdf", pdf_bytes, "application/pdf")},
        headers=_auth(user1_token),
    )
    assert second_response.status_code == 200
    second_body = second_response.json()
    assert second_body["status"] == "unchanged"
    assert second_body["document_id"] == first_body["document_id"]

    versions_after = await api_client.get(
        f"/workspaces/{workspace_id}/documents/{first_body['document_id']}/versions",
        headers=_auth(user1_token),
    )
    assert len(versions_after.json()) == version_count_before


async def test_reuploading_changed_bytes_creates_a_new_version(api_client, user1_token):
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)
    original_bytes = FIXTURE_PDF.read_bytes()
    # Append a comment/no-op byte sequence after %%EOF-adjacent content so the hash
    # changes while the file often still parses (PyMuPDF tolerates trailing garbage).
    changed_bytes = original_bytes + f"\n% test-variant {uuid.uuid4().hex}\n".encode()

    first_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("changing.pdf", original_bytes, "application/pdf")},
        headers=_auth(user1_token),
    )
    first_body = first_response.json()
    job_one = await _poll_job_until_terminal(
        api_client, user1_token, workspace_id, first_body["job_id"]
    )
    assert job_one["status"] == "ready", job_one.get("failure_reason")

    second_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("changing.pdf", changed_bytes, "application/pdf")},
        headers=_auth(user1_token),
    )
    assert second_response.status_code == 202
    second_body = second_response.json()
    assert second_body["document_id"] == first_body["document_id"]
    assert second_body["document_version_id"] != first_body["document_version_id"]

    job_two = await _poll_job_until_terminal(
        api_client, user1_token, workspace_id, second_body["job_id"]
    )
    assert job_two["status"] == "ready", job_two.get("failure_reason")

    versions_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents/{first_body['document_id']}/versions",
        headers=_auth(user1_token),
    )
    versions = versions_response.json()
    assert len(versions) == 2
    version_by_id = {v["id"]: v for v in versions}
    assert version_by_id[first_body["document_version_id"]]["is_current"] is False
    assert version_by_id[first_body["document_version_id"]]["superseded_at"] is not None
    assert version_by_id[second_body["document_version_id"]]["is_current"] is True
