import uuid

from pydantic import BaseModel


class MemberAdd(BaseModel):
    user_id: uuid.UUID
    role: str


class MemberRoleUpdate(BaseModel):
    role: str


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
