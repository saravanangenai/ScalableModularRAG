import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import AuditLog


def write_audit_log(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    metadata: dict | None = None,
) -> None:
    """Adds an audit_log row to the current transaction. Callers run this only after the RLS
    GUC is already set for tenant_id (every caller in apps/api is past a role-check
    dependency by the time it writes here), since audit_log is itself RLS-protected."""
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata,
        )
    )
