"""Requires `docker compose up -d postgres` (infra/docker-compose.yml) and infra/.env
populated from infra/.env.example. Not runnable in a sandbox without Docker/Postgres.

Single-tenant schema (see migration 0001): no tenant_id columns. Isolation is per-workspace,
enforced at the application layer plus workspace-scoped Row-Level Security as
defense-in-depth (migration 0002, specs/030-workspace-rbac-filtering). This test round-trips
the workspace -> document -> document_version chain directly against the ORM (not through
apps/api), so it sets the RLS GUC itself before writing to a protected table — exactly what
apps/api/deps/rbac.py::require_workspace_role does for every real request. Nothing is
committed; the `db_session` fixture rolls back at teardown.
"""

from packages.db.models import Document, DocumentVersion, User, Workspace
from tests.integration.test_rls import _set_scope


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

    _set_scope(db_session, workspace.id)  # documents is RLS-protected; workspaces is not

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
