from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from packages.auth.config import Settings as AuthSettings
from packages.auth.context import get_or_provision_user
from packages.auth.jwt import verify_token
from packages.db.models import User
from packages.exceptions import AuthenticationError

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db_session),
) -> User:
    """JWT-only identity resolution (no API key support) — used by routes with no
    tenant/workspace in the path yet (creating a tenant, listing my own tenants), where an
    API key (which is always scoped to one tenant already) wouldn't make sense."""
    if credentials is None:
        raise AuthenticationError("missing bearer token")

    claims = verify_token(credentials.credentials, AuthSettings())
    sub = claims["sub"]
    email = claims.get("email") or f"{sub}@unknown.invalid"
    display_name = claims.get("name") or claims.get("preferred_username") or sub
    return await get_or_provision_user(session, sub, email, display_name)
