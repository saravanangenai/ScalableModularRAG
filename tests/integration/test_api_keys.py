"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

import uuid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_api_key_create_use_revoke_lifecycle(api_client, user1_token):
    tenant_response = await api_client.post(
        "/tenants",
        json={"name": "API Key Tenant", "slug": f"apikey-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_id = tenant_response.json()["id"]

    create_response = await api_client.post(
        f"/tenants/{tenant_id}/api-keys",
        json={"scopes": ["documents:read"]},
        headers=_auth(user1_token),
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["key"].startswith("mmrag_")
    key_id, plaintext_key = body["id"], body["key"]

    # The plaintext key authenticates like a bearer token for this tenant.
    use_response = await api_client.get(
        f"/tenants/{tenant_id}/workspaces", headers=_auth(plaintext_key)
    )
    assert use_response.status_code == 200

    # It does NOT work against a different (wrong) tenant — no leak of which reason.
    other_tenant_response = await api_client.post(
        "/tenants",
        json={"name": "Other Tenant", "slug": f"other-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    other_tenant_id = other_tenant_response.json()["id"]
    wrong_tenant_response = await api_client.get(
        f"/tenants/{other_tenant_id}/workspaces", headers=_auth(plaintext_key)
    )
    assert wrong_tenant_response.status_code == 401

    revoke_response = await api_client.delete(
        f"/tenants/{tenant_id}/api-keys/{key_id}", headers=_auth(user1_token)
    )
    assert revoke_response.status_code == 204

    revoked_use_response = await api_client.get(
        f"/tenants/{tenant_id}/workspaces", headers=_auth(plaintext_key)
    )
    assert revoked_use_response.status_code == 401


async def test_list_api_keys_never_exposes_hash_or_plaintext(api_client, user1_token):
    tenant_response = await api_client.post(
        "/tenants",
        json={"name": "List Keys Tenant", "slug": f"listkeys-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_id = tenant_response.json()["id"]

    await api_client.post(
        f"/tenants/{tenant_id}/api-keys", json={"scopes": []}, headers=_auth(user1_token)
    )

    list_response = await api_client.get(
        f"/tenants/{tenant_id}/api-keys", headers=_auth(user1_token)
    )
    assert list_response.status_code == 200
    for key in list_response.json():
        assert "key_hash" not in key
        assert "key" not in key
