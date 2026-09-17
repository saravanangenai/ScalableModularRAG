"""table intelligence: document_tables + table_cells

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-16 00:00:00.000000

Adds normalized table storage for specs/051-table-intelligence: document_tables (one row
per extracted table — summary, schema, raw-content object storage key) and table_cells (one
row per normalized cell, keyed (document_id, table_id, row_index, column_name) per
specs/architecture/05-multimodal-strategy.md §2). Nothing queries table_cells yet — that's
an explicit non-goal (a future text-to-SQL-style spec); this migration only makes the data
durable and queryable in principle.

Both tables are RLS-protected from creation, using the exact one-hop EXISTS-join-through-
documents policy shape migration 0002 already established for document_versions/
ingestion_jobs — no new isolation pattern. Unlike 0002, there's no pre-existing data to
retrofit: both tables are brand new, so RLS is applied in the same migration that creates
them rather than as a later, separate pass.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUC = "app.current_workspace_id"
_TABLES = ["document_tables", "table_cells"]


def _policy_condition(table: str) -> str:
    """Same one-hop EXISTS-join shape as migration 0002's document_versions/ingestion_jobs
    policies — both new tables carry a direct document_id column for exactly this reason."""
    return (
        f"EXISTS (SELECT 1 FROM documents d WHERE d.id = {table}.document_id "
        f"AND d.workspace_id = current_setting('{_GUC}', true)::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "document_tables",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("table_index", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("object_storage_key", sa.String(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("schema_json", JSONB(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_document_tables_document_id", "document_tables", ["document_id"]
    )
    op.create_index(
        "ix_document_tables_document_version_id", "document_tables", ["document_version_id"]
    )

    op.create_table(
        "table_cells",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "table_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_tables.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_name", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "table_id", "row_index", "column_name", name="uq_table_cells_table_row_column"
        ),
    )
    op.create_index("ix_table_cells_document_id", "table_cells", ["document_id"])
    op.create_index("ix_table_cells_table_id", "table_cells", ["table_id"])

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        condition = _policy_condition(table)
        op.execute(
            f"CREATE POLICY {table}_workspace_isolation ON {table} "
            f"USING ({condition}) WITH CHECK ({condition})"
        )


def downgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")

    op.drop_table("table_cells")
    op.drop_table("document_tables")
