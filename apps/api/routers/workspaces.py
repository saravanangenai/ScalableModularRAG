import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.auth import get_current_user
from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.members import MemberAdd, MemberOut, MemberRoleUpdate
from apps.api.schemas.workspaces import WorkspaceCreate, WorkspaceOut
from packages.db.audit import write_audit_log
from packages.db.models import User, Workspace, WorkspaceMember

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


async def _get_member_or_404(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember:
    member = await session.get(
        WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}
    )
    if member is None:
        raise HTTPException(status_code=404, detail="not found")
    return member


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


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_workspace_members(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[MemberOut]:
    """specs/071-search-frontend: the frontend's Members tab needs to see who's in a
    workspace before it can offer role-change/remove actions on them — this route didn't
    exist before 071 (071's plan.md documents this as a discovered-during-implementation
    deviation, not a silent scope change). viewer-and-up, matching every other read route on
    this workspace (seeing your co-members is normal, not privileged, unlike the owner-only
    write actions below)."""
    result = await session.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == access.workspace_id)
    )
    return [
        MemberOut(user_id=user.id, email=user.email, display_name=user.display_name, role=member.role)
        for member, user in result.all()
    ]


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
    member = await _get_member_or_404(session, access.workspace_id, user_id)
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
    member = await _get_member_or_404(session, access.workspace_id, user_id)
    await session.delete(member)
    write_audit_log(
        session,
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id if access.user else None,
        action="workspace_member.remove",
        resource_type="workspace_member",
        resource_id=user_id,
    )
