import uuid

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import TenantMember, User, WorkspaceMember


async def get_or_provision_user(
    session: AsyncSession, sub: str, email: str, display_name: str
) -> User:
    """Just-in-time provisioning: looks up a users row by the IdP's stable sub claim,
    creating one on first sight. auth_provider_subject is UNIQUE (migration 0002), so a
    race between two concurrent first-requests for the same new sub is resolved by
    catching the losing insert's IntegrityError and re-querying rather than erroring."""
    existing = await session.scalar(select(User).where(User.auth_provider_subject == sub))
    if existing is not None:
        return existing

    user = User(email=email, display_name=display_name, auth_provider_subject=sub)
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return await session.scalar(select(User).where(User.auth_provider_subject == sub))
    return user


async def resolve_tenant_role(
    session: AsyncSession, user_id: uuid.UUID, tenant_id: uuid.UUID
) -> str | None:
    """tenant_members carries no tenant_id-of-its-own / isn't RLS-protected (see
    packages.db.models.TENANT_SCOPED_TABLES), so this is safe to query before the RLS GUC
    is set — it's what determines what to set the GUC to in the first place."""
    return await session.scalar(
        select(TenantMember.role).where(
            TenantMember.tenant_id == tenant_id, TenantMember.user_id == user_id
        )
    )


async def resolve_workspace_role(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> tuple[str, uuid.UUID] | None:
    """Returns (role, tenant_id) or None if the caller has no membership in this workspace.
    tenant_id comes along for free here (denormalized onto workspace_members, see
    011-auth-and-workspaces/plan.md) because the caller needs it to set the RLS GUC, and
    workspaces itself can't be queried for it before the GUC is set."""
    row = (
        await session.execute(
            select(WorkspaceMember.role, WorkspaceMember.tenant_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
    ).first()
    return (row.role, row.tenant_id) if row is not None else None


async def set_tenant_scope(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Sets app.current_tenant_id for the remainder of this session's transaction, engaging
    the Row-Level Security policies from 010-metadata-db-and-object-storage."""
    await session.execute(
        text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
