import datetime
import uuid

from pydantic import BaseModel


class ApiKeyCreate(BaseModel):
    scopes: list[str] = []


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    key: str  # plaintext — returned exactly once, at creation
    scopes: list[str]
    created_at: datetime.datetime


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    scopes: list[str]
    created_at: datetime.datetime
    revoked_at: datetime.datetime | None

    model_config = {"from_attributes": True}
