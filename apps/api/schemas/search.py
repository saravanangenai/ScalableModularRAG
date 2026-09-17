import uuid

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=8, ge=1, le=50)


class SearchResultOut(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    filename: str | None
    content_type: str | None
    page_number: int | None
    chunk_index: int | None
    table_index: int | None
    image_index: int | None
    image_path: str | None
    text: str | None
    score: float

    model_config = {"from_attributes": True}


class SearchResponse(BaseModel):
    results: list[SearchResultOut]
