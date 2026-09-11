"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

from tests.integration.test_upload_and_ingest import _auth, _create_workspace


async def test_api_key_create_use_revoke_lifecycle(api_client, user1_token):
    workspace_id = await _create_workspace(api_client, user1_token)

    create_response = await api_client.post(
        f"/workspaces/{workspace_id}/api-keys",
        json={"scopes": ["documents:read"]},
        headers=_auth(user1_token),
    )
    assert create_response.status_code == 201
    body = create_response.json()
    assert body["key"].startswith("mmrag_")
    key_id, plaintext_key = body["id"], body["key"]

    # The plaintext key authenticates like a bearer token for its own workspace.
    use_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents", headers=_auth(plaintext_key)
    )
    assert use_response.status_code == 200

    # It does NOT work against a different workspace — same opaque failure either way.
    other_workspace_id = await _create_workspace(api_client, user1_token)
    wrong_workspace_response = await api_client.get(
        f"/workspaces/{other_workspace_id}/documents", headers=_auth(plaintext_key)
    )
    assert wrong_workspace_response.status_code == 401

    revoke_response = await api_client.delete(
        f"/workspaces/{workspace_id}/api-keys/{key_id}", headers=_auth(user1_token)
    )
    assert revoke_response.status_code == 204

    revoked_use_response = await api_client.get(
        f"/workspaces/{workspace_id}/documents", headers=_auth(plaintext_key)
    )
    assert revoked_use_response.status_code == 401


async def test_list_api_keys_never_exposes_hash_or_plaintext(api_client, user1_token):
    workspace_id = await _create_workspace(api_client, user1_token)

    await api_client.post(
        f"/workspaces/{workspace_id}/api-keys",
        json={"scopes": []},
        headers=_auth(user1_token),
    )

    list_response = await api_client.get(
        f"/workspaces/{workspace_id}/api-keys", headers=_auth(user1_token)
    )
    assert list_response.status_code == 200
    for key in list_response.json():
        assert "key_hash" not in key
        assert "key" not in key
