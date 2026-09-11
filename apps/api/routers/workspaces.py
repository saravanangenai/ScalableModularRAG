import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.auth import get_current_user
from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.members import MemberAdd, MemberRoleUpdate
from apps.api.schemas.workspaces import WorkspaceCreate, WorkspaceOut
from packages.db.audit import write_audit_log
from packages.db.models import User, Workspace, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Workspace:
    workspace = Workspace(name=body.name, created_by=user.id)
    session.add(workspace)
    await session.flush()
    # Creator is the first member; without this nobody could manage the workspace afterward.
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    )
    return workspace


@router.get("", response_model=list[WorkspaceOut])
async def list_my_workspaces(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[Workspace]:
    result = await session.execute(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
    )
    return list(result.scalars().all())


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
            role=body.role,
        )
    )
    write_audit_log(
        session,
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id if access.user else None,
        action="workspace_member.add",
        resource_type="workspace_member",
        resource_id=body.user_id,
        metadata={"role": body.role},
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
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id if access.user else None,
        action="workspace_member.role_change",
        resource_type="workspace_member",
        resource_id=user_id,
        metadata={"role": body.role},
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
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id if access.user else None,
        action="workspace_member.remove",
        resource_type="workspace_member",
        resource_id=user_id,
    )
