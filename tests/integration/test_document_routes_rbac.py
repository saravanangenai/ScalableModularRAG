"""Requires real Postgres, MinIO, Keycloak (does not need Qdrant/Memurai/a worker/OpenAI —
these tests only exercise auth/RBAC on the new routes, not real ingestion)."""

import uuid

from packages.db.models import User

from tests.integration.test_upload_and_ingest import _auth, _create_tenant_and_workspace


async def test_upload_requires_editor_role_not_just_viewer(
    api_client, user1_token, user2_token, db_session
):
    tenant_id, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    await api_client.get("/tenants", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_member_response = await api_client.post(
        f"/tenants/{tenant_id}/members",
        json={"user_id": str(user2.id), "role": "member"},
        headers=_auth(user1_token),
    )
    assert add_member_response.status_code == 201

    add_workspace_member_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )
    assert add_workspace_member_response.status_code == 201

    upload_response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")},
        headers=_auth(user2_token),
    )
    assert upload_response.status_code == 403

    list_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents", headers=_auth(user2_token)
    )
    assert list_response.status_code == 200


async def test_document_and_job_routes_404_for_non_member(api_client, user1_token):
    random_workspace_id = uuid.uuid4()
    random_document_id = uuid.uuid4()
    random_job_id = uuid.uuid4()

    list_response = await api_client.get(
        f"/workspaces/{random_workspace_id}/documents", headers=_auth(user1_token)
    )
    assert list_response.status_code == 404

    doc_response = await api_client.get(
        f"/workspaces/{random_workspace_id}/documents/{random_document_id}",
        headers=_auth(user1_token),
    )
    assert doc_response.status_code == 404

    job_response = await api_client.get(
        f"/workspaces/{random_workspace_id}/jobs/{random_job_id}", headers=_auth(user1_token)
    )
    assert job_response.status_code == 404


async def test_no_token_is_rejected_on_new_routes(api_client):
    workspace_id = uuid.uuid4()
    response = await api_client.get(f"/workspaces/{workspace_id}/documents")
    assert response.status_code == 401


async def test_upload_rejects_non_pdf_content_type(api_client, user1_token):
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("x.txt", b"not a pdf", "text/plain")},
        headers=_auth(user1_token),
    )
    assert response.status_code == 415


async def test_upload_rejects_pdf_content_type_with_bad_magic_bytes(api_client, user1_token):
    _, workspace_id = await _create_tenant_and_workspace(api_client, user1_token)

    response = await api_client.post(
        f"/workspaces/{workspace_id}/documents",
        files={"file": ("x.pdf", b"not actually a pdf", "application/pdf")},
        headers=_auth(user1_token),
    )
    assert response.status_code == 415
