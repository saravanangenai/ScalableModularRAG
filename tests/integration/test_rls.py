"""Requires `docker compose up -d postgres` (infra/docker-compose.yml) and infra/.env
populated from infra/.env.example. Not runnable in a sandbox without Docker/Postgres.

Proves the Row-Level Security policies from migration 0001 actually hold for the role
running migrations (FORCE ROW LEVEL SECURITY is required for that, since Postgres exempts
table owners from RLS otherwise): with `app.current_tenant_id` unset, tenant-scoped tables
are invisible; with it set, only the matching tenant's rows are visible.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from packages.db.models import Tenant, User, Workspace


def _set_tenant(session: Session, tenant_id) -> None:
    session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )


def test_rls_fails_closed_without_guc_and_scopes_by_tenant_with_guc(db_engine):
    with Session(bind=db_engine) as setup_session:
        user = User(
            email="rls-user@example.com",
            display_name="RLS User",
            auth_provider_subject="sub-rls",
        )
        tenant_a = Tenant(name="Tenant A", slug="tenant-a-rls", plan_tier="free")
        tenant_b = Tenant(name="Tenant B", slug="tenant-b-rls", plan_tier="free")
        setup_session.add_all([user, tenant_a, tenant_b])
        setup_session.flush()
        user_id, tenant_a_id, tenant_b_id = user.id, tenant_a.id, tenant_b.id

        _set_tenant(setup_session, tenant_a_id)
        setup_session.add(Workspace(tenant_id=tenant_a_id, name="WS-A", created_by=user_id))
        setup_session.flush()

        _set_tenant(setup_session, tenant_b_id)
        setup_session.add(Workspace(tenant_id=tenant_b_id, name="WS-B", created_by=user_id))
        setup_session.commit()

    # No GUC set for this transaction -> fails closed, zero rows visible.
    with Session(bind=db_engine) as session:
        rows = (
            session.query(Workspace)
            .filter(Workspace.tenant_id.in_([tenant_a_id, tenant_b_id]))
            .all()
        )
        assert rows == []

    # GUC set to tenant A -> only tenant A's workspace visible, not tenant B's.
    with Session(bind=db_engine) as session:
        _set_tenant(session, tenant_a_id)
        rows = (
            session.query(Workspace)
            .filter(Workspace.tenant_id.in_([tenant_a_id, tenant_b_id]))
            .all()
        )
        assert [w.tenant_id for w in rows] == [tenant_a_id]
