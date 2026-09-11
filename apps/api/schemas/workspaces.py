import datetime
import uuid

from pydantic import BaseModel


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
