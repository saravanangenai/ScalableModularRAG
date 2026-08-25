import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.members import MemberAdd, MemberRoleUpdate
from packages.db.audit import write_audit_log
from packages.db.models import WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("/{workspace_id}/members", status_code=201)
async def add_workspace_member(
    body: MemberAdd,
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    session.add(
        WorkspaceMember(
            workspace_id=access.workspace_id,
            user_id=body.user_id,
            tenant_id=access.tenant_id,
            role=body.role,
        )
    )
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id,
        action="workspace_member.add",
        resource_type="workspace_member",
        resource_id=body.user_id,
        metadata={"role": body.role, "workspace_id": str(access.workspace_id)},
    )
    return {"status": "added"}


@router.patch("/{workspace_id}/members/{user_id}")
async def update_workspace_member_role(
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    member = await session.get(
        WorkspaceMember, {"workspace_id": access.workspace_id, "user_id": user_id}
    )
    member.role = body.role
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id,
        action="workspace_member.role_change",
        resource_type="workspace_member",
        resource_id=user_id,
        metadata={"role": body.role, "workspace_id": str(access.workspace_id)},
    )
    return {"status": "updated"}


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
async def remove_workspace_member(
    user_id: uuid.UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    member = await session.get(
        WorkspaceMember, {"workspace_id": access.workspace_id, "user_id": user_id}
    )
    await session.delete(member)
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id,
        action="workspace_member.remove",
        resource_type="workspace_member",
        resource_id=user_id,
        metadata={"workspace_id": str(access.workspace_id)},
    )
