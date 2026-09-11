import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from packages.db.models import User, WorkspaceMember


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


async def resolve_workspace_role(
    session: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID
) -> str | None:
    """Returns the caller's role in this workspace, or None if they have no membership."""
    return await session.scalar(
        select(WorkspaceMember.role).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
    )
