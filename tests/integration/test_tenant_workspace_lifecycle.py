"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

import uuid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _get_internal_user_id(api_client, token: str) -> str:
    # GET /tenants doesn't return "who am I", but any authenticated call JIT-provisions the
    # caller; we read their internal id back out via the tenant they own after creation.
    response = await api_client.post(
        "/tenants",
        json={"name": "id-probe", "slug": f"id-probe-{uuid.uuid4().hex[:8]}"},
        headers=_auth(token),
    )
    return response.json()["id"]


async def test_create_tenant_makes_caller_owner(api_client, user1_token):
    response = await api_client.post(
        "/tenants",
        json={"name": "Lifecycle Tenant", "slug": f"lifecycle-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    assert response.status_code == 201
    tenant_id = response.json()["id"]

    # Owner can immediately do an admin-only action (create a workspace).
    ws_response = await api_client.post(
        f"/tenants/{tenant_id}/workspaces", json={"name": "Default"}, headers=_auth(user1_token)
    )
    assert ws_response.status_code == 201
    assert ws_response.json()["tenant_id"] == tenant_id


async def test_member_role_cannot_create_workspace_but_can_list(
    api_client, user1_token, user2_token, db_session
):
    from packages.db.models import User

    create_response = await api_client.post(
        "/tenants",
        json={"name": "RBAC Tenant", "slug": f"rbac-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_id = create_response.json()["id"]

    # Force user2's JIT provisioning, then look up their internal id directly.
    await api_client.get("/tenants", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_response = await api_client.post(
        f"/tenants/{tenant_id}/members",
        json={"user_id": str(user2.id), "role": "member"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201

    forbidden_response = await api_client.post(
        f"/tenants/{tenant_id}/workspaces",
        json={"name": "ShouldFail"},
        headers=_auth(user2_token),
    )
    assert forbidden_response.status_code == 403

    allowed_response = await api_client.get(
        f"/tenants/{tenant_id}/workspaces", headers=_auth(user2_token)
    )
    assert allowed_response.status_code == 200


async def test_workspace_owner_can_add_member_others_cannot(
    api_client, user1_token, user2_token, db_session
):
    from packages.db.models import User

    tenant_response = await api_client.post(
        "/tenants",
        json={"name": "Workspace RBAC Tenant", "slug": f"ws-rbac-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_id = tenant_response.json()["id"]

    ws_response = await api_client.post(
        f"/tenants/{tenant_id}/workspaces", json={"name": "Default"}, headers=_auth(user1_token)
    )
    workspace_id = ws_response.json()["id"]

    await api_client.get("/tenants", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    # user2 is not a workspace member yet -> 404, not 403 (per 06-security-model.md §5).
    forbidden_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user2_token),
    )
    assert forbidden_response.status_code == 404

    # Workspace owner (user1) can add user2.
    add_response = await api_client.post(
        f"/workspaces/{workspace_id}/members",
        json={"user_id": str(user2.id), "role": "viewer"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201
