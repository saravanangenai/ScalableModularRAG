import uuid
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from packages.auth.api_keys import is_api_key, resolve_active_api_key
from packages.auth.config import Settings as AuthSettings
from packages.auth.context import (
    get_or_provision_user,
    resolve_tenant_role,
    resolve_workspace_role,
    set_tenant_scope,
)
from packages.auth.jwt import verify_token
from packages.auth.rbac import tenant_role_at_least, workspace_role_at_least
from packages.db.models import User
from packages.exceptions import AuthenticationError, AuthorizationError, MembershipNotFoundError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class TenantAccess:
    tenant_id: uuid.UUID
    user: User | None  # None when authenticated via API key
    role: str


@dataclass
class WorkspaceAccess:
    workspace_id: uuid.UUID
    tenant_id: uuid.UUID
    user: User
    role: str


def require_tenant_role(min_role: str):
    async def dependency(
        tenant_id: uuid.UUID,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
        session: AsyncSession = Depends(get_db_session),
    ) -> TenantAccess:
        if credentials is None:
            raise AuthenticationError("missing bearer token")
        token = credentials.credentials

        if is_api_key(token):
            # api_keys IS RLS-protected, unlike tenant_members/workspace_members — see
            # plan.md "API keys as an alternative credential". Tentatively scope to the
            # path's claimed tenant_id; the key only resolves if it actually belongs there.
            await set_tenant_scope(session, tenant_id)
            api_key = await resolve_active_api_key(session, token)
            if api_key is None:
                raise AuthenticationError("invalid api key")
            return TenantAccess(tenant_id=tenant_id, user=None, role="owner")

        claims = verify_token(token, AuthSettings())
        sub = claims["sub"]
        email = claims.get("email") or f"{sub}@unknown.invalid"
        display_name = claims.get("name") or claims.get("preferred_username") or sub
        user = await get_or_provision_user(session, sub, email, display_name)

        role = await resolve_tenant_role(session, user.id, tenant_id)
        if role is None:
            raise MembershipNotFoundError("caller is not a member of this tenant")
        if not tenant_role_at_least(role, min_role):
            raise AuthorizationError("insufficient tenant role")

        await set_tenant_scope(session, tenant_id)
        return TenantAccess(tenant_id=tenant_id, user=user, role=role)

    return dependency


def require_workspace_role(min_role: str):
    async def dependency(
        workspace_id: uuid.UUID,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
        session: AsyncSession = Depends(get_db_session),
    ) -> WorkspaceAccess:
        # API keys have no workspace granularity in this data model (02-data-model.md) — only
        # JWTs are accepted here, per plan.md.
        if credentials is None:
            raise AuthenticationError("missing bearer token")

        claims = verify_token(credentials.credentials, AuthSettings())
        sub = claims["sub"]
        email = claims.get("email") or f"{sub}@unknown.invalid"
        display_name = claims.get("name") or claims.get("preferred_username") or sub
        user = await get_or_provision_user(session, sub, email, display_name)

        resolved = await resolve_workspace_role(session, user.id, workspace_id)
        if resolved is None:
            raise MembershipNotFoundError("caller is not a member of this workspace")
        role, tenant_id = resolved
        if not workspace_role_at_least(role, min_role):
            raise AuthorizationError("insufficient workspace role")

        await set_tenant_scope(session, tenant_id)
        return WorkspaceAccess(
            workspace_id=workspace_id, tenant_id=tenant_id, user=user, role=role
        )

    return dependency
