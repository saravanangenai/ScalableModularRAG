from packages.db.models import TENANT_SCOPED_TABLES, Base

EXPECTED_TABLES = {
    "tenants",
    "users",
    "tenant_members",
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
    "usage_quotas",
}


def test_every_data_model_table_is_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_tenant_scoped_tables_have_tenant_id_column():
    for table_name in TENANT_SCOPED_TABLES:
        table = Base.metadata.tables[table_name]
        assert "tenant_id" in table.columns, f"{table_name} is missing tenant_id"


def test_document_versions_unique_per_document_and_version_number():
    table = Base.metadata.tables["document_versions"]
    unique_constraints = {
        tuple(col.name for col in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("document_id", "version_number") in unique_constraints
