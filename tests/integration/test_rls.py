"""Requires real Postgres only (native service, per infra/.env) — deliberately does not go
through apps/api or Keycloak. This proves the Row-Level Security policies added by migration
0002 (packages/db/migrations/versions/0002_workspace_rls.py) hold at the database level,
independent of any application code ever forgetting a WHERE clause or a route guard.

db_session connects with the exact same app DB credentials apps/api uses
(packages.db.config.Settings via packages.db.session._build_sync_engine) — the same user
that owns every table it migrated — so this also proves FORCE ROW LEVEL SECURITY is doing
its job: Postgres exempts table owners from RLS unless FORCE is set, and the app's own
connection has no other elevated privilege that would let it bypass RLS.
"""

import uuid

import psycopg
from sqlalchemy import text

from packages.db.config import Settings as DbSettings
from packages.db.models import (
    ApiKey,
    AuditLog,
    Document,
    DocumentTable,
    DocumentVersion,
    IngestionJob,
    TableCell,
    User,
    Workspace,
)
# Aliased, not reimplemented: this file used to hand-roll its own set_config(...) call —
# delegate to the same helper production code (and the Celery worker) uses instead.
from packages.db.rls import set_workspace_scope_sync as _set_scope


def _seed_two_workspaces(db_session):
    """Creates two workspaces each with one document/document_version/ingestion_job/api_key/
    audit_log row. Inserts into RLS-protected tables happen with the GUC set to the owning
    workspace first — WITH CHECK requires it, matching how apps/api's own request flow always
    sets the GUC (require_workspace_role) before any route handler writes a row."""
    user = User(
        email=f"rls-test-{uuid.uuid4()}@example.com",
        display_name="RLS Test",
        auth_provider_subject=str(uuid.uuid4()),
    )
    db_session.add(user)
    db_session.flush()

    workspace_x = Workspace(name="Workspace X", created_by=user.id)
    workspace_y = Workspace(name="Workspace Y", created_by=user.id)
    db_session.add_all([workspace_x, workspace_y])
    db_session.flush()

    records = {}
    for label, workspace in (("x", workspace_x), ("y", workspace_y)):
        _set_scope(db_session, workspace.id)

        document = Document(
            workspace_id=workspace.id,
            filename=f"{label}.pdf",
            content_hash_current=f"hash-{label}",
            status="ready",
            created_by=user.id,
        )
        db_session.add(document)
        db_session.flush()

        document_version = DocumentVersion(
            document_id=document.id,
            version_number=1,
            content_hash=f"hash-{label}",
            object_storage_key=f"{workspace.id}/{document.id}/hash-{label}.pdf",
            page_count=1,
            is_current=True,
        )
        db_session.add(document_version)
        db_session.flush()

        ingestion_job = IngestionJob(
            document_id=document.id, document_version_id=document_version.id, status="ready"
        )
        db_session.add(ingestion_job)

        document_table = DocumentTable(
            document_id=document.id,
            document_version_id=document_version.id,
            table_index=1,
            page_number=1,
            object_storage_key=f"{workspace.id}/{document.id}/{document_version.id}/tables/1.csv",
            summary=f"summary-{label}",
            row_count=1,
        )
        db_session.add(document_table)
        db_session.flush()

        table_cell = TableCell(
            table_id=document_table.id,
            document_id=document.id,
            row_index=0,
            column_name="col_a",
            value=f"value-{label}",
        )
        db_session.add(table_cell)

        api_key = ApiKey(
            workspace_id=workspace.id,
            key_hash=f"hash-{label}-{uuid.uuid4()}",
            scopes=["documents:read"],
            created_by=user.id,
        )
        db_session.add(api_key)

        audit_log = AuditLog(
            workspace_id=workspace.id,
            actor_user_id=user.id,
            action="document.upload",
            resource_type="document",
            resource_id=document.id,
        )
        db_session.add(audit_log)
        db_session.flush()

        records[label] = {
            "workspace": workspace,
            "document": document,
            "document_version": document_version,
            "ingestion_job": ingestion_job,
            "document_table": document_table,
            "table_cell": table_cell,
            "api_key": api_key,
            "audit_log": audit_log,
        }

    return records


def test_direct_column_tables_are_isolated_by_workspace_guc(db_session):
    records = _seed_two_workspaces(db_session)

    for table, model in (("documents", Document), ("api_keys", ApiKey), ("audit_log", AuditLog)):
        _set_scope(db_session, records["x"]["workspace"].id)
        visible = db_session.query(model).all()
        visible_workspace_ids = {row.workspace_id for row in visible}
        assert visible_workspace_ids == {records["x"]["workspace"].id}, table

        _set_scope(db_session, records["y"]["workspace"].id)
        visible = db_session.query(model).all()
        visible_workspace_ids = {row.workspace_id for row in visible}
        assert visible_workspace_ids == {records["y"]["workspace"].id}, table


def test_joined_tables_are_isolated_by_workspace_guc(db_session):
    records = _seed_two_workspaces(db_session)

    for table, model, fk_field in (
        ("document_versions", DocumentVersion, "document_id"),
        ("ingestion_jobs", IngestionJob, "document_id"),
        ("document_tables", DocumentTable, "document_id"),
        ("table_cells", TableCell, "document_id"),
    ):
        _set_scope(db_session, records["x"]["workspace"].id)
        visible_document_ids = {getattr(row, fk_field) for row in db_session.query(model).all()}
        assert visible_document_ids == {records["x"]["document"].id}, table

        _set_scope(db_session, records["y"]["workspace"].id)
        visible_document_ids = {getattr(row, fk_field) for row in db_session.query(model).all()}
        assert visible_document_ids == {records["y"]["document"].id}, table


def test_unset_guc_denies_all_rows_fail_closed(db_session):
    """A connection that never calls set_workspace_scope at all (e.g. a route that forgot to
    go through require_workspace_role) must never return someone else's rows. This needs a
    genuinely fresh backend session opened outside SQLAlchemy's connection pool — a pooled
    connection previously touched by another test's set_config call would see '' (the
    placeholder's post-RESET default) rather than the true never-set NULL state, since the
    GUC placeholder's existence is backend-session-scoped, not transaction-scoped, and the
    pool reuses physical connections across tests. Either outcome (a cast error on '', or
    zero rows on NULL) is "fail closed" — this asserts the property, not the specific path."""
    _seed_two_workspaces(db_session)
    db_session.commit()  # make it visible to the separate raw connection below

    settings = DbSettings()
    dsn = (
        f"host={settings.postgres_host} port={settings.postgres_port} "
        f"dbname={settings.postgres_db} user={settings.postgres_user} "
        f"password={settings.postgres_password}"
    )
    with psycopg.connect(dsn) as fresh_connection:
        with fresh_connection.cursor() as cursor:
            try:
                cursor.execute("SELECT * FROM documents")
                assert cursor.fetchall() == []
            except psycopg.errors.InvalidTextRepresentation:
                pass  # current_setting(...)::uuid raised on the unset GUC — also fail-closed


def test_random_guc_denies_all_rows(db_session):
    _seed_two_workspaces(db_session)

    _set_scope(db_session, uuid.uuid4())
    assert db_session.query(Document).all() == []
    assert db_session.query(ApiKey).all() == []


def test_workspaces_and_members_tables_are_not_rls_protected(db_session):
    """workspace_members/workspaces must stay queryable without the GUC set — the caller's
    role has to be resolvable from workspace_members before the GUC can exist."""
    rows = db_session.execute(
        text(
            "SELECT relname, relrowsecurity FROM pg_class "
            "WHERE relname IN ('workspaces', 'workspace_members')"
        )
    ).fetchall()
    assert {row[0]: row[1] for row in rows} == {"workspaces": False, "workspace_members": False}
