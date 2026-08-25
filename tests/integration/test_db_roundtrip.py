"""Requires `docker compose up -d postgres` (infra/docker-compose.yml) and infra/.env
populated from infra/.env.example. Not runnable in a sandbox without Docker/Postgres.

Every tenant-scoped table is under FORCE ROW LEVEL SECURITY (see migration 0001), so any
insert/read against workspaces/documents/document_versions must happen with
`app.current_tenant_id` set for the current transaction — this test sets it via SET LOCAL
right after creating the tenant, matching how `011-auth-and-workspaces` will set it per
request. Nothing is committed; the `db_session` fixture rolls back at teardown, so the GUC
setting (transaction-scoped) stays valid for the whole test.
"""

from sqlalchemy import text

from packages.db.models import Document, DocumentVersion, Tenant, User, Workspace


def test_tenant_workspace_document_version_chain_round_trips(db_session):
    user = User(
        email="creator@example.com",
        display_name="Creator",
        auth_provider_subject="sub-123",
    )
    tenant = Tenant(name="Acme", slug="acme", plan_tier="pro")
    db_session.add_all([user, tenant])
    db_session.flush()

    db_session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant.id)},
    )

    workspace = Workspace(tenant_id=tenant.id, name="Default", created_by=user.id)
    db_session.add(workspace)
    db_session.flush()

    document = Document(
        workspace_id=workspace.id,
        tenant_id=tenant.id,
        filename="contract.pdf",
        content_hash_current="hash-v1",
        status="ready",
        created_by=user.id,
    )
    db_session.add(document)
    db_session.flush()

    document_version = DocumentVersion(
        document_id=document.id,
        tenant_id=tenant.id,
        version_number=1,
        content_hash="hash-v1",
        object_storage_key=f"{tenant.id}/{workspace.id}/{document.id}/hash-v1.pdf",
        page_count=10,
        is_current=True,
    )
    db_session.add(document_version)
    db_session.flush()

    db_session.expire_all()

    fetched_tenant = db_session.get(Tenant, tenant.id)
    fetched_workspace = db_session.get(Workspace, workspace.id)
    fetched_document = db_session.get(Document, document.id)
    fetched_version = db_session.get(DocumentVersion, document_version.id)

    assert fetched_tenant.slug == "acme"
    assert fetched_workspace.tenant_id == tenant.id
    assert fetched_document.workspace_id == workspace.id
    assert fetched_document.tenant_id == tenant.id
    assert fetched_version.document_id == document.id
    assert fetched_version.tenant_id == tenant.id
    assert fetched_version.object_storage_key == document_version.object_storage_key
