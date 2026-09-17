from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.audit import AuditLogEntryOut, AuditLogPage
from packages.db.models import AuditLog

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["audit"])


@router.get("/audit-log", response_model=AuditLogPage)
async def list_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> AuditLogPage:
    """Read-only view over the audit_log rows workspaces.py/api_keys.py already write —
    specs/070-api-hardening. RLS (packages/db/migrations/versions/0002_workspace_rls.py)
    scopes the query to access.workspace_id the same way every other protected table does;
    owner-only, matching api_keys.py/workspaces.py's existing pattern."""
    total = await session.scalar(
        select(func.count()).select_from(AuditLog).where(AuditLog.workspace_id == access.workspace_id)
    )
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.workspace_id == access.workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [AuditLogEntryOut.model_validate(row) for row in result.scalars().all()]
    return AuditLogPage(items=items, total=total or 0)
