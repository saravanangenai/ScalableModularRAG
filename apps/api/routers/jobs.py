import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.jobs import JobOut
from packages.db.models import IngestionJob

router = APIRouter(prefix="/workspaces/{workspace_id}/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> IngestionJob:
    job = await session.scalar(
        select(IngestionJob).where(
            IngestionJob.id == job_id, IngestionJob.tenant_id == access.tenant_id
        )
    )
    if job is None:
        raise HTTPException(status_code=404, detail="not found")
    return job
