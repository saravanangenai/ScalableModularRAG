"""Requires the same live stack as test_upload_and_ingest.py (Postgres, MinIO, Keycloak,
Qdrant, Memurai, a running Celery worker). Does not need a real OPENAI_API_KEY — a
corrupt/unparseable PDF fails at the parsing stage, before any embedding call happens."""

import os

from tests.integration.test_upload_and_ingest import (
    _auth,
    _create_tenant_and_workspace,
    _poll_job_until_terminal,
)

# Passes the router's "%PDF-" magic-byte check but has no valid PDF structure behind it —
# PyMuPDF fails to open it.
CORRUPT_PDF_BYTES = b"%PDF-1.4\n" + os.urandom(256)


async def test_corrupt_pdf_fails_the_job_without_damaging_prior_state(api_client, user1_token):
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("corrupt.pdf", CORRUPT_PDF_BYTES, "application/pdf")},
        headers=_auth(user1_token),
    )
    assert upload_response.status_code == 202
    body = upload_response.json()

    job = await _poll_job_until_terminal(
        api_client, user1_token, workspace_id, body["job_id"], timeout=60
    )
    assert job["status"] == "failed"
    assert job["failure_stage"] == "parsing"
    assert job["failure_reason"]
    assert job["retry_count"] >= 1

    doc_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents/{body['document_id']}", headers=_auth(user1_token)
    )
    doc_body = doc_response.json()
    # No version ever reached "ready" for this document, so it should never claim to be.
    assert doc_body["current_version_id"] is None
    assert doc_body["status"] != "ready"


async def test_reuploading_identical_corrupt_content_retries_instead_of_short_circuiting(
    api_client, user1_token
):
    """The content_hash_current guard fixed in plan.md's Implementation findings: a
    document whose only version ever failed must NOT be treated as 'unchanged' on a later
    identical re-upload — it must retry."""
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    first_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("still-corrupt.pdf", CORRUPT_PDF_BYTES, "application/pdf")},
        headers=_auth(user1_token),
    )
    first_body = first_response.json()
    await _poll_job_until_terminal(
        api_client, user1_token, workspace_id, first_body["job_id"], timeout=60
    )

    second_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("still-corrupt.pdf", CORRUPT_PDF_BYTES, "application/pdf")},
        headers=_auth(user1_token),
    )
    # Must NOT be treated as "unchanged" (200) — no version ever succeeded.
    assert second_response.status_code == 202
    second_body = second_response.json()
    assert second_body["status"] == "queued"
    assert second_body["document_version_id"] != first_body["document_version_id"]
