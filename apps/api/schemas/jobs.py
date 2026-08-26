import datetime
import uuid

from pydantic import BaseModel


class JobOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    status: str
    failure_stage: str | None
    failure_reason: str | None
    retry_count: int
    started_at: datetime.datetime | None
    finished_at: datetime.datetime | None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
