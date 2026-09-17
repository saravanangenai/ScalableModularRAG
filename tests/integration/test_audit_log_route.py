"""Requires real Postgres + Keycloak (specs/070-api-hardening)."""

from packages.db.models import User

from tests.integration.test_upload_and_ingest import _auth, _create_workspace


async def test_owner_sees_real_audit_log_rows_after_a_member_change(
    api_client, user1_token, user2_token, db_session
):
    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.get("/workspaces", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201

    audit_response = await api_client.get(
        f"/workspaces/{workspace_id}/audit-log", headers=_auth(user1_token)
    )
    assert audit_response.status_code == 200
    body = audit_response.json()
    assert body["total"] == 1
    entry = body["items"][0]
    assert entry["action"] == "workspace_member.add"
    assert entry["resource_id"] == str(user2.id)
    assert entry["metadata_json"] == {"role": "viewer"}


async def test_non_owner_gets_403_on_audit_log(api_client, user1_token, user2_token, db_session):
    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.get("/workspaces", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )

    audit_response = await api_client.get(
        f"/workspaces/{workspace_id}/audit-log", headers=_auth(user2_token)
    )
    assert audit_response.status_code == 403
