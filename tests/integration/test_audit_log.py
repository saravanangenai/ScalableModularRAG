"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

import uuid

from sqlalchemy import text

from tests.integration.test_upload_and_ingest import _auth, _create_workspace


async def test_membership_and_api_key_actions_write_audit_rows(
    api_client, user1_token, user2_token, db_session
):
    from packages.db.models import User

    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.get("/workspaces", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201

    remove_response = await api_client.delete(
        f"/workspaces/{workspace_id}/members/{user2.id}", headers=_auth(user1_token)
    )
    assert remove_response.status_code == 204

    key_response = await api_client.post(
        f"/workspaces/{workspace_id}/api-keys",
        json={"scopes": []},
        headers=_auth(user1_token),
    )
    key_id = key_response.json()["id"]
    await api_client.delete(
        f"/workspaces/{workspace_id}/api-keys/{key_id}", headers=_auth(user1_token)
    )

    rows = db_session.execute(
        text(
            "SELECT action, resource_type, resource_id FROM audit_log "
            "WHERE workspace_id = :wid ORDER BY created_at"
        ),
        {"wid": workspace_id},
    ).fetchall()

    actions = [row.action for row in rows]
    assert actions == [
        "workspace_member.add",
        "workspace_member.remove",
        "api_key.create",
        "api_key.revoke",
    ]
    assert str(rows[0].resource_id) == str(user2.id)
    assert rows[2].resource_id == rows[3].resource_id == uuid.UUID(key_id)
