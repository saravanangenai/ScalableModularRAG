"""Requires `docker compose up -d postgres` (infra/docker-compose.yml) and infra/.env
populated from infra/.env.example. Not runnable in a sandbox without Docker/Postgres.

Single-tenant schema (see migration 0001): no tenant_id columns, no Row-Level Security.
Isolation is per-workspace at the application layer, so this test just round-trips the
workspace -> document -> document_version chain directly. Nothing is committed; the
`db_session` fixture rolls back at teardown.
"""

from packages.db.models import Document, DocumentVersion, User, Workspace


def test_workspace_document_version_chain_round_trips(db_session):
    user = User(
        email="creator@example.com",
        display_name="Creator",
        auth_provider_subject="sub-123",
    )
    db_session.add(user)
    db_session.flush()

    workspace = Workspace(name="Default", created_by=user.id)
    db_session.add(workspace)
    db_session.flush()

    document = Document(
        workspace_id=workspace.id,
        filename="contract.pdf",
        content_hash_current="hash-v1",
        status="ready",
        created_by=user.id,
    )
    db_session.add(document)
    db_session.flush()

    document_version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_hash="hash-v1",
        object_storage_key=f"{workspace.id}/{document.id}/hash-v1.pdf",
        page_count=10,
        is_current=True,
    )
    db_session.add(document_version)
    db_session.flush()

    db_session.expire_all()

    fetched_workspace = db_session.get(Workspace, workspace.id)
    fetched_document = db_session.get(Document, document.id)
    fetched_version = db_session.get(DocumentVersion, document_version.id)

    assert fetched_workspace.name == "Default"
    assert fetched_document.workspace_id == workspace.id
    assert fetched_version.document_id == document.id
    assert fetched_version.object_storage_key == document_version.object_storage_key
