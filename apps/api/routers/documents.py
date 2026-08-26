import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.deps.db import get_db_session
from apps.api.deps.rbac import WorkspaceAccess, require_workspace_role
from apps.api.schemas.documents import (
    DocumentOut,
    DocumentVersionOut,
    UploadAccepted,
    UploadUnchanged,
)
from packages.db.models import Document, DocumentVersion, IngestionJob
from packages.ingestion.versioning import content_hash, is_unchanged
from packages.storage.client import StorageClient
from packages.storage.keys import document_key
from workers.celery_app import run_ingestion_job

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["documents"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


@router.post("/documents")
async def upload_document(
    file: UploadFile,
    response: Response,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
    session: AsyncSession = Depends(get_db_session),
) -> UploadAccepted | UploadUnchanged:
    if file.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=415, detail="only PDF uploads are supported")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="file is not a valid PDF")

    file_hash = content_hash(data)

    existing_document = await session.scalar(
        select(Document).where(
            Document.workspace_id == access.workspace_id, Document.filename == file.filename
        )
    )

    if (
        existing_document is not None
        and existing_document.current_version_id is not None
        and is_unchanged(file_hash, existing_document.content_hash_current)
    ):
        response.status_code = 200
        return UploadUnchanged(
            document_id=existing_document.id,
            document_version_id=existing_document.current_version_id,
            status="unchanged",
        )

    if existing_document is None:
        document = Document(
            workspace_id=access.workspace_id,
            tenant_id=access.tenant_id,
            filename=file.filename,
            content_hash_current=file_hash,
            status="queued",
            created_by=access.user.id,
        )
        session.add(document)
        await session.flush()
        version_number = 1
    else:
        document = existing_document
        latest_version_number = await session.scalar(
            select(DocumentVersion.version_number)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version_number.desc())
            .limit(1)
        )
        version_number = (latest_version_number or 0) + 1

    storage_key = document_key(access.tenant_id, access.workspace_id, document.id, file_hash)
    StorageClient().upload(storage_key, data)

    document_version = DocumentVersion(
        document_id=document.id,
        tenant_id=access.tenant_id,
        version_number=version_number,
        content_hash=file_hash,
        object_storage_key=storage_key,
        page_count=0,
        is_current=False,
    )
    session.add(document_version)
    await session.flush()

    job = IngestionJob(
        document_id=document.id,
        document_version_id=document_version.id,
        tenant_id=access.tenant_id,
        status="queued",
        retry_count=0,
    )
    session.add(job)
    await session.flush()

    await session.commit()

    run_ingestion_job.delay(str(job.id), str(access.tenant_id))

    response.status_code = 202
    return UploadAccepted(
        document_id=document.id,
        document_version_id=document_version.id,
        job_id=job.id,
        status="queued",
    )


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[Document]:
    result = await session.execute(
        select(Document).where(Document.workspace_id == access.workspace_id)
    )
    return list(result.scalars().all())


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(
    document_id: uuid.UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> Document:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == access.workspace_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="not found")
    return document


@router.get("/documents/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_document_versions(
    document_id: uuid.UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentVersion]:
    document = await session.scalar(
        select(Document).where(
            Document.id == document_id, Document.workspace_id == access.workspace_id
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="not found")

    result = await session.execute(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number)
    )
    return list(result.scalars().all())
