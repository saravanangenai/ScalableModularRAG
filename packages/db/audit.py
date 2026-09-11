import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import AuditLog


def write_audit_log(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID,
    metadata: dict | None = None,
) -> None:
    """Adds an audit_log row to the current transaction. workspace_id is nullable for the
    few actions that aren't scoped to an existing workspace."""
    session.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata_json=metadata,
        )
    )
