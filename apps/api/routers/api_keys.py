import datetime
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.api_keys import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from packages.auth.api_keys import generate_api_key
from packages.db.audit import write_audit_log
from packages.db.models import ApiKey
from packages.exceptions import AuthenticationError

router = APIRouter(prefix="/workspaces/{workspace_id}/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    if access.user is None:
        raise AuthenticationError("creating an api key requires user authentication")

    plaintext_key, key_hash = generate_api_key()
    api_key = ApiKey(
        workspace_id=access.workspace_id,
        key_hash=key_hash,
        scopes=body.scopes,
        created_by=access.user.id,
    )
    session.add(api_key)
    await session.flush()
    write_audit_log(
        session,
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id,
        action="api_key.create",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"scopes": body.scopes},
    )
    return {
        "id": api_key.id,
        "key": plaintext_key,
        "scopes": api_key.scopes,
        "created_at": api_key.created_at,
    }


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> list[ApiKey]:
    result = await session.execute(
        select(ApiKey).where(ApiKey.workspace_id == access.workspace_id)
    )
    return list(result.scalars().all())


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(
    key_id: uuid.UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("owner")),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    api_key = await session.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id, ApiKey.workspace_id == access.workspace_id
        )
    )
    if api_key is None:
        return
    api_key.revoked_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    write_audit_log(
        session,
        workspace_id=access.workspace_id,
        actor_user_id=access.user.id if access.user else None,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=key_id,
    )
