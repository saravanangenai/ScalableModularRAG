"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

import uuid

from sqlalchemy import text


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_membership_and_api_key_actions_write_audit_rows(
    api_client, user1_token, user2_token, db_session
):
    from packages.db.models import User

    tenant_response = await api_client.post(
        "/tenants",
        json={"name": "Audit Tenant", "slug": f"audit-{uuid.uuid4().hex[:8]}"},
        headers=_auth(user1_token),
    )
    tenant_id = tenant_response.json()["id"]

    await api_client.get("/tenants", headers=_auth(user2_token))
    user2 = db_session.query(User).filter(User.email == "testuser2@example.com").one()

    add_response = await api_client.post(
        f"/tenants/{tenant_id}/members",
        json={"user_id": str(user2.id), "role": "member"},
        headers=_auth(user1_token),
    )
    assert add_response.status_code == 201

    remove_response = await api_client.delete(
        f"/tenants/{tenant_id}/members/{user2.id}", headers=_auth(user1_token)
    )
    assert remove_response.status_code == 204

    key_response = await api_client.post(
        f"/tenants/{tenant_id}/api-keys", json={"scopes": []}, headers=_auth(user1_token)
    )
    key_id = key_response.json()["id"]
    await api_client.delete(
        f"/tenants/{tenant_id}/api-keys/{key_id}", headers=_auth(user1_token)
    )

    db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
    )
    rows = db_session.execute(
        text(
            "SELECT action, resource_type, resource_id FROM audit_log "
            "WHERE tenant_id = :tid ORDER BY created_at"
        ),
        {"tid": tenant_id},
    ).fetchall()

    actions = [row.action for row in rows]
    assert actions == [
        "tenant_member.add",
        "tenant_member.remove",
        "api_key.create",
        "api_key.revoke",
    ]
    assert str(rows[0].resource_id) == str(user2.id)
    assert rows[2].resource_id == rows[3].resource_id == uuid.UUID(key_id)
