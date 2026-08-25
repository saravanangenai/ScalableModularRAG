import uuid

from pydantic import BaseModel


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str


class MemberRoleUpdate(BaseModel):
    role: str
