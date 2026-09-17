from packages.db.models import Base

EXPECTED_TABLES = {
    "users",
    "workspaces",
    "workspace_members",
    "documents",
    "document_versions",
    "ingestion_jobs",
    "conversations",
    "messages",
    "message_feedback",
    "api_keys",
    "audit_log",
    "document_tables",
    "table_cells",
}


def test_every_data_model_table_is_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_no_table_carries_a_tenant_id_column():
    for table_name, table in Base.metadata.tables.items():
        assert "tenant_id" not in table.columns, f"{table_name} still has tenant_id"


def test_api_keys_and_audit_log_are_workspace_scoped():
    assert "workspace_id" in Base.metadata.tables["api_keys"].columns
    assert "workspace_id" in Base.metadata.tables["audit_log"].columns


def test_document_versions_unique_per_document_and_version_number():
    table = Base.metadata.tables["document_versions"]
    unique_constraints = {
        tuple(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("document_id", "version_number") in unique_constraints


def test_users_auth_provider_subject_is_unique():
    table = Base.metadata.tables["users"]
    assert table.columns["auth_provider_subject"].unique


def test_table_cells_unique_per_table_row_and_column():
    table = Base.metadata.tables["table_cells"]
    unique_constraints = {
        tuple(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("table_id", "row_index", "column_name") in unique_constraints


def test_document_tables_and_table_cells_are_reachable_from_documents():
    """Both are RLS-protected via a one-hop join to documents (migration 0003), not a direct
    workspace_id column — same shape as document_versions/ingestion_jobs."""
    assert "document_id" in Base.metadata.tables["document_tables"].columns
    assert "document_id" in Base.metadata.tables["table_cells"].columns
    assert "workspace_id" not in Base.metadata.tables["document_tables"].columns
    assert "workspace_id" not in Base.metadata.tables["table_cells"].columns
