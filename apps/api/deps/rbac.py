import uuid
from dataclasses import dataclass

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from packages.auth.api_keys import is_api_key, resolve_active_api_key
from packages.auth.config import Settings as AuthSettings
from packages.auth.context import get_or_provision_user, resolve_workspace_role
from packages.auth.jwt import verify_token
from packages.auth.rbac import workspace_role_at_least
from packages.db.models import User
from packages.exceptions import AuthenticationError, AuthorizationError, MembershipNotFoundError

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class WorkspaceAccess:
    workspace_id: uuid.UUID
    user: User | None  # None when authenticated via a workspace-scoped API key
    role: str


def require_workspace_role(min_role: str):
    async def dependency(
        workspace_id: uuid.UUID,
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
        session: AsyncSession = Depends(get_db_session),
    ) -> WorkspaceAccess:
        if credentials is None:
            raise AuthenticationError("missing bearer token")
        token = credentials.credentials

        if is_api_key(token):
            api_key = await resolve_active_api_key(session, token)
            if api_key is None or api_key.workspace_id != workspace_id:
                # Same opaque failure whether the key is bad or simply scoped elsewhere.
                raise AuthenticationError("invalid api key")
            # A workspace-scoped key acts with owner-equivalent authority within its
            # workspace; routes that attribute a write to a user still require a JWT.
            return WorkspaceAccess(workspace_id=workspace_id, user=None, role="owner")

        claims = verify_token(token, AuthSettings())
        sub = claims["sub"]
        email = claims.get("email") or f"{sub}@unknown.invalid"
        display_name = claims.get("name") or claims.get("preferred_username") or sub
        user = await get_or_provision_user(session, sub, email, display_name)

        role = await resolve_workspace_role(session, user.id, workspace_id)
        if role is None:
            raise MembershipNotFoundError("caller is not a member of this workspace")
        if not workspace_role_at_least(role, min_role):
            raise AuthorizationError("insufficient workspace role")

        return WorkspaceAccess(workspace_id=workspace_id, user=user, role=role)

    return dependency
