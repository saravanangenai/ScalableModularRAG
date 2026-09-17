import datetime
import uuid

from pydantic import BaseModel


class AuditLogEntryOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID
    metadata_json: dict | None
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class AuditLogPage(BaseModel):
    items: list[AuditLogEntryOut]
    total: int
