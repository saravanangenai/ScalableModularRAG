"""Requires real Keycloak + real Postgres, see test_auth_flow.py."""

import asyncio

from sqlalchemy import select


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_first_request_provisions_exactly_one_user_row(
    api_client, create_keycloak_user, mint_token, db_session
):
    from packages.db.models import User

    username, password = create_keycloak_user()
    token = mint_token(username, password)

    response = await api_client.get("/workspaces", headers=_auth(token))
    assert response.status_code == 200

    rows = db_session.scalars(
        select(User).where(User.email == f"{username}@example.com")
    ).all()
    assert len(rows) == 1


async def test_concurrent_first_requests_still_provision_exactly_one_user_row(
    api_client, create_keycloak_user, mint_token, db_session
):
    from packages.db.models import User

    username, password = create_keycloak_user()
    token = mint_token(username, password)

    responses = await asyncio.gather(
        *[api_client.get("/workspaces", headers=_auth(token)) for _ in range(5)]
    )
    assert all(r.status_code == 200 for r in responses)

    rows = db_session.scalars(
        select(User).where(User.email == f"{username}@example.com")
    ).all()
    assert len(rows) == 1
