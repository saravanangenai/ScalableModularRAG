import datetime
import uuid

from pydantic import BaseModel


class TenantCreate(BaseModel):
    name: str
    slug: str


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan_tier: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}


class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    created_at: datetime.datetime

    model_config = {"from_attributes": True}
