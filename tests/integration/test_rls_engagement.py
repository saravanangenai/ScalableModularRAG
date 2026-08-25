"""Requires real Keycloak + real Postgres, see test_auth_flow.py.

Proves apps/api/deps/rbac.py's set_tenant_scope call actually reaches the Row-Level Security
policies from 010-metadata-db-and-object-storage — not just that the API's own WHERE clauses
happen to filter correctly (defense in depth: even without those WHERE clauses, RLS alone
must be enough)."""

import uuid

from sqlalchemy import text


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_rls_hides_other_tenants_workspaces_at_the_db_layer(
    api_client, user1_token, user2_token, db_session
):
    tenant_a_response = await api_client.post(
        "/tenants",
        json={"name": "Tenant A", "slug": f"rls-a-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_a_id = tenant_a_response.json()["id"]
    ws_a_response = await api_client.post(
        f"/tenants/{tenant_a_id}/workspaces", json={"name": "WS-A"}, headers=_auth(user1_token)
    )
    assert ws_a_response.status_code == 201

    tenant_b_response = await api_client.post(
        "/tenants",
        json={"name": "Tenant B", "slug": f"rls-b-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user2_token),
    )
    tenant_b_id = tenant_b_response.json()["id"]
    ws_b_response = await api_client.post(
        f"/tenants/{tenant_b_id}/workspaces", json={"name": "WS-B"}, headers=_auth(user2_token)
    )
    assert ws_b_response.status_code == 201

    # Raw query, deliberately with NO WHERE clause on tenant_id — RLS alone must scope this.
    db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_a_id}
    )
    visible_names = {
        row[0]
        for row in db_session.execute(text("SELECT name FROM workspaces")).fetchall()
    }
    assert "WS-A" in visible_names
    assert "WS-B" not in visible_names
