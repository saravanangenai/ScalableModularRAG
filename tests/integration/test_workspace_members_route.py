"""Requires real Postgres + Keycloak (specs/071-search-frontend)."""

from packages.db.models import User

from tests.integration.test_upload_and_ingest import _auth, _create_workspace


async def test_owner_sees_self_and_added_member(api_client, user1_token, user2_token, db_session):
    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.get("/workspaces", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201

    members_response = await api_client.get(
        f"/workspaces/{workspace_id}/members", headers=_auth(user1_token)
    )
    assert members_response.status_code == 200
    members = members_response.json()
    roles_by_email = {m["email"]: m["role"] for m in members}
    assert roles_by_email["testuser@example.com"] == "owner"
    assert roles_by_email["testuser2@example.com"] == "viewer"


async def test_viewer_can_also_list_members(api_client, user1_token, user2_token, db_session):
    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.get("/workspaces", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )

    members_response = await api_client.get(
        f"/workspaces/{workspace_id}/members", headers=_auth(user2_token)
    )
    assert members_response.status_code == 200
    assert len(members_response.json()) == 2


async def test_non_member_gets_404_on_members_list(api_client, user1_token):
    import uuid

    random_workspace_id = uuid.uuid4()

    response = await api_client.get(
        f"/workspaces/{random_workspace_id}/members", headers=_auth(user1_token)
    )
    assert response.status_code == 404
