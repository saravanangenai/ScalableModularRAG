"""workspace-scoped row-level security

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-14 00:00:00.000000

Adds workspace-scoped Row-Level Security as defense-in-depth behind the existing
application-layer `workspace_id` filtering, per specs/030-workspace-rbac-filtering/plan.md
and the decision specs/012-single-tenant-simplification deferred here. Policies key off the
`app.current_workspace_id` session GUC (packages/db/rls.py::set_workspace_scope), set once
per request by apps/api/deps/rbac.py::require_workspace_role after the caller's role has
already been resolved and authorized — RLS is a second, independent check, not the primary
authorization mechanism.

Protected: documents, api_keys, audit_log (direct workspace_id column) and
document_versions, ingestion_jobs (no direct workspace_id column — policy joins to
documents). Deliberately NOT protected: workspaces/workspace_members (the caller's role must
be resolved from workspace_members *before* the GUC can be set — same bootstrap-ordering
reasoning specs/011-auth-and-workspaces used for the old tenant GUC) and
conversations/messages/message_feedback (no route reads or writes them yet; deferred to
whichever spec first implements chat).

FORCE ROW LEVEL SECURITY is required, not just ENABLE: every app connection uses the single
`postgres_user` configured in packages/db/config.py, which owns every table it migrated —
and Postgres exempts table owners from RLS by default even when it's enabled. Without FORCE,
this migration would silently do nothing for the application's own connections.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUC = "app.current_workspace_id"

# Tables with a direct workspace_id column: a single equality check against the GUC.
_DIRECT_TABLES = ["documents", "api_keys", "audit_log"]

# Tables reachable only via documents.workspace_id (no direct column) — see 02-data-model.md
# §0's as-built schema. Policy uses an EXISTS join instead of a denormalized column
# (specs/030-workspace-rbac-filtering/plan.md's Alternatives considered).
_JOINED_TABLES = ["document_versions", "ingestion_jobs"]


def _policy_condition(table: str) -> str:
    """The USING/WITH CHECK body for `table` — a direct workspace_id equality check, or an
    EXISTS join through documents for a table with no direct column (see _JOINED_TABLES)."""
    if table in _JOINED_TABLES:
        return (
            f"EXISTS (SELECT 1 FROM documents d WHERE d.id = {table}.document_id "
            f"AND d.workspace_id = current_setting('{_GUC}', true)::uuid)"
        )
    return f"workspace_id = current_setting('{_GUC}', true)::uuid"


def upgrade() -> None:
    for table in _DIRECT_TABLES + _JOINED_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        condition = _policy_condition(table)
        op.execute(
            f"CREATE POLICY {table}_workspace_isolation ON {table} "
            f"USING ({condition}) WITH CHECK ({condition})"
        )


def downgrade() -> None:
    for table in _DIRECT_TABLES + _JOINED_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_workspace_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
