import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.auth import get_current_user
from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import TenantAccess, require_tenant_role
from apps.api.schemas.members import MemberAdd, MemberRoleUpdate
from apps.api.schemas.tenants import TenantCreate, TenantOut, WorkspaceCreate, WorkspaceOut
from packages.db.audit import write_audit_log
from packages.db.models import Tenant, TenantMember, User, Workspace, WorkspaceMember
from packages.exceptions import AuthenticationError

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=TenantOut, status_code=201)
async def create_tenant(
    body: TenantCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> Tenant:
    tenant = Tenant(name=body.name, slug=body.slug, plan_tier="free")
    session.add(tenant)
    await session.flush()
    session.add(TenantMember(tenant_id=tenant.id, user_id=user.id, role="owner"))
    return tenant


@router.get("", response_model=list[TenantOut])
async def list_my_tenants(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[Tenant]:
    # tenants/tenant_members carry no RLS (see TENANT_SCOPED_TABLES) — this is an
    # application-level filter, not RLS, per plan.md's API contract note.
    result = await session.execute(
        select(Tenant).join(TenantMember, TenantMember.tenant_id == Tenant.id).where(
            TenantMember.user_id == user.id
        )
    )
    return list(result.scalars().all())


@router.post("/{tenant_id}/workspaces", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    access: TenantAccess = Depends(require_tenant_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> Workspace:
    if access.user is None:
        raise AuthenticationError("creating a workspace requires user authentication")
    workspace = Workspace(tenant_id=access.tenant_id, name=body.name, created_by=access.user.id)
    session.add(workspace)
    await session.flush()
    # Without this, nobody could ever manage the new workspace's membership afterward —
    # workspace_members is the only thing require_workspace_role checks, and tenant admin
    # status doesn't imply workspace membership.
    session.add(
        WorkspaceMember(
            workspace_id=workspace.id,
            user_id=access.user.id,
            tenant_id=access.tenant_id,
            role="owner",
        )
    )
    return workspace


@router.get("/{tenant_id}/workspaces", response_model=list[WorkspaceOut])
async def list_workspaces(
    access: TenantAccess = Depends(require_tenant_role("member")),
    session: AsyncSession = Depends(get_db_session),
) -> list[Workspace]:
    result = await session.execute(
        select(Workspace).where(Workspace.tenant_id == access.tenant_id)
    )
    return list(result.scalars().all())


@router.post("/{tenant_id}/members", status_code=201)
async def add_tenant_member(
    body: MemberAdd,
    access: TenantAccess = Depends(require_tenant_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    session.add(TenantMember(tenant_id=access.tenant_id, user_id=body.user_id, role=body.role))
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id if access.user else None,
        action="tenant_member.add",
        resource_type="tenant_member",
        resource_id=body.user_id,
        metadata={"role": body.role},
    )
    return {"status": "added"}


@router.patch("/{tenant_id}/members/{user_id}")
async def update_tenant_member_role(
    user_id: uuid.UUID,
    body: MemberRoleUpdate,
    access: TenantAccess = Depends(require_tenant_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    member = await session.get(TenantMember, {"tenant_id": access.tenant_id, "user_id": user_id})
    member.role = body.role
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id if access.user else None,
        action="tenant_member.role_change",
        resource_type="tenant_member",
        resource_id=user_id,
        metadata={"role": body.role},
    )
    return {"status": "updated"}


@router.delete("/{tenant_id}/members/{user_id}", status_code=204)
async def remove_tenant_member(
    user_id: uuid.UUID,
    access: TenantAccess = Depends(require_tenant_role("admin")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    member = await session.get(TenantMember, {"tenant_id": access.tenant_id, "user_id": user_id})
    await session.delete(member)
    write_audit_log(
        session,
        tenant_id=access.tenant_id,
        actor_user_id=access.user.id if access.user else None,
        action="tenant_member.remove",
        resource_type="tenant_member",
        resource_id=user_id,
    )
