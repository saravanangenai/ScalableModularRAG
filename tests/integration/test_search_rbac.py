"""Requires real Postgres, MinIO, Keycloak, Qdrant, and Memurai, plus a running Celery
worker and a real OPENAI_API_KEY — same stack as test_upload_and_ingest.py. Not runnable in
this environment (no Qdrant/MinIO/Keycloak here — see specs/030-workspace-rbac-filtering/
tasks.md's Group 4 note); written and reviewed, pending that stack to actually execute.

Exercises specs/030-workspace-rbac-filtering's retrieval-time authorization boundary: the
mandatory, server-constructed workspace_id filter apps/api/routers/search.py applies via
packages/retrieval, on top of the same require_workspace_role guard every other route uses.
"""

import uuid

from tests.integration.test_upload_and_ingest import (
    FIXTURE_PDF,
    _auth,
    _create_workspace,
    _poll_job_until_terminal,
)


async def _ingest_one_document(api_client, token: str, workspace_id: str) -> str:
    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("sample.pdf", FIXTURE_PDF.read_bytes(), "application/pdf")},
        headers=_auth(token),
    )
    assert upload_response.status_code == 202
    body = upload_response.json()

    job = await _poll_job_until_terminal(api_client, token, workspace_id, body["job_id"])
    assert job["status"] == "ready", job.get("failure_reason")

    return body["document_id"]


async def _seed_two_workspaces(api_client, user1_token, user2_token):
    """Workspace A (user1, sole member) and workspace B (user2, sole member), each with one
    real ingested document — the two-workspace fixture pattern
    tests/integration/test_document_routes_rbac.py already uses, extended to cover a real
    ingested document rather than just an empty workspace."""
    workspace_a = await _create_workspace(api_client, user1_token)
    workspace_b = await _create_workspace(api_client, user2_token)

    document_a = await _ingest_one_document(api_client, user1_token, workspace_a)
    document_b = await _ingest_one_document(api_client, user2_token, workspace_b)

    return {
        "workspace_a": workspace_a,
        "workspace_b": workspace_b,
        "document_a": document_a,
        "document_b": document_b,
    }


async def test_member_search_scoped_to_own_workspace(api_client, user1_token, user2_token):
    seeded = await _seed_two_workspaces(api_client, user1_token, user2_token)

    response = await api_client.post(
        f"/workspaces/{seeded['workspace_a']}/search",
        json={"query": "what does this document say", "k": 8},
        headers=_auth(user1_token),
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) > 0
    for result in body["results"]:
        assert result["document_id"] == seeded["document_a"]
        assert result["document_id"] != seeded["document_b"]


async def test_non_member_search_rejected(api_client, user1_token, user2_token):
    seeded = await _seed_two_workspaces(api_client, user1_token, user2_token)

    # user1 is not a member of workspace B.
    response = await api_client.post(
        f"/workspaces/{seeded['workspace_b']}/search",
        json={"query": "what does this document say", "k": 8},
        headers=_auth(user1_token),
    )
    assert response.status_code in (403, 404)
    body_text = response.text
    assert seeded["workspace_b"] not in body_text
    assert seeded["document_b"] not in body_text


async def test_search_requires_authentication(api_client, user1_token):
    workspace_id = await _create_workspace(api_client, user1_token)

    response = await api_client.post(
        f"/workspaces/{workspace_id}/search", json={"query": "anything", "k": 8}
    )
    assert response.status_code == 401


async def test_search_rejects_invalid_request_bodies(api_client, user1_token):
    workspace_id = await _create_workspace(api_client, user1_token)

    empty_query = await api_client.post(
        f"/workspaces/{workspace_id}/search",
        json={"query": "", "k": 8},
        headers=_auth(user1_token),
    )
    assert empty_query.status_code == 422

    k_too_low = await api_client.post(
        f"/workspaces/{workspace_id}/search",
        json={"query": "valid query", "k": 0},
        headers=_auth(user1_token),
    )
    assert k_too_low.status_code == 422

    k_too_high = await api_client.post(
        f"/workspaces/{workspace_id}/search",
        json={"query": "valid query", "k": 51},
        headers=_auth(user1_token),
    )
    assert k_too_high.status_code == 422


async def test_nonexistent_workspace_search_returns_404_not_500(api_client, user1_token):
    random_workspace_id = uuid.uuid4()

    response = await api_client.post(
        f"/workspaces/{random_workspace_id}/search",
        json={"query": "anything", "k": 8},
        headers=_auth(user1_token),
    )
    assert response.status_code == 404
