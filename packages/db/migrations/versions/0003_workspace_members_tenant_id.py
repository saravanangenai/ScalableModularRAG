"""workspace_members tenant_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-24 18:33:24.077102

Denormalizes tenant_id onto workspace_members (see 011-auth-and-workspaces/plan.md): a
workspace-scoped request needs to know which tenant a workspace_id belongs to in order to
set the app.current_tenant_id RLS GUC, but the workspaces table itself is RLS-protected, so
that lookup returns nothing before the GUC is set. workspace_members is deliberately not
RLS-protected (same reasoning as tenant_members), so carrying tenant_id there too resolves
role and tenant scope in one bootstrap-safe query.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspace_members",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
    )
    op.execute(
        "UPDATE workspace_members SET tenant_id = workspaces.tenant_id "
        "FROM workspaces WHERE workspaces.id = workspace_members.workspace_id"
    )
    op.alter_column("workspace_members", "tenant_id", nullable=False)
    op.create_index(
        "ix_workspace_members_tenant_id", "workspace_members", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_members_tenant_id", table_name="workspace_members")
    op.drop_column("workspace_members", "tenant_id")
