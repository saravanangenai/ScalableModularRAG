import datetime
import uuid

from pydantic import BaseModel


class DocumentOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    filename: str
    content_hash_current: str
    status: str
    current_version_id: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime

    model_config = {"from_attributes": True}


class DocumentVersionOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    content_hash: str
    page_count: int
    is_current: bool
    superseded_at: datetime.datetime | None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class UploadAccepted(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    job_id: uuid.UUID
    status: str  # "queued"


class UploadUnchanged(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    status: str  # "unchanged"
