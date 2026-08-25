"""Requires real Keycloak (localhost:8080, mm-rag realm via scripts/setup_keycloak_dev.py)
and real Postgres (infra/docker-compose.yml's postgres, or an equivalent native install)."""

import uuid


async def test_health_endpoint_requires_no_auth(api_client):
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_no_token_is_rejected(api_client):
    response = await api_client.get("/tenants")
    assert response.status_code == 401


async def test_garbage_token_is_rejected(api_client):
    response = await api_client.get("/tenants", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


async def test_valid_token_but_not_a_tenant_member_is_404(api_client, user1_token):
    random_tenant_id = uuid.uuid4()
    response = await api_client.get(
        f"/tenants/{random_tenant_id}/workspaces",
        headers={"Authorization": f"Bearer {user1_token}"},
    )
    assert response.status_code == 404


async def test_valid_token_for_a_member_succeeds(api_client, user1_token):
    create_response = await api_client.post(
        "/tenants",
        json={"name": "Auth Flow Tenant", "slug": f"auth-flow-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {user1_token}"},
    )
    assert create_response.status_code == 201
    tenant_id = create_response.json()["id"]

    list_response = await api_client.get(
        f"/tenants/{tenant_id}/workspaces", headers={"Authorization": f"Bearer {user1_token}"}
    )
    assert list_response.status_code == 200
    assert list_response.json() == []
