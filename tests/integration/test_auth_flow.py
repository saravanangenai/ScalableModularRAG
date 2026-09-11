"""Requires real Keycloak (localhost:8080, mm-rag realm via scripts/setup_keycloak_dev.py)
and real Postgres (infra/docker-compose.yml's postgres, or an equivalent native install)."""

import uuid


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_health_endpoint_requires_no_auth(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_no_token_is_rejected(api_client):
    response = await api_client.get("/workspaces")
    assert response.status_code == 401


async def test_garbage_token_is_rejected(api_client):
    response = await api_client.get("/workspaces", headers=_auth("not-a-jwt"))
    assert response.status_code == 401


async def test_valid_token_but_not_a_workspace_member_is_404(api_client, user1_token):
    random_workspace_id = uuid.uuid4()
    response = await api_client.get(
        f"/workspaces/{random_workspace_id}/documents", headers=_auth(user1_token)
    )
    assert response.status_code == 404


async def test_valid_token_can_create_and_list_own_workspaces(api_client, user1_token):
    create_response = await api_client.post(
        "/workspaces",
        json={"name": f"Auth Flow WS {uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    assert create_response.status_code == 201
    workspace_id = create_response.json()["id"]

    list_response = await api_client.get("/workspaces", headers=_auth(user1_token))
    assert list_response.status_code == 200
    assert workspace_id in [w["id"] for w in list_response.json()]
