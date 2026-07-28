from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: int
    filename: str
    content_type: str | None = None
    source_type: str
    chunk_count: int
    created_at: datetime | None = None


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=4000)
    limit: int = Field(default=5, ge=1, le=20)


class SearchResultResponse(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    content: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectDocumentResponse(BaseModel):
    id: UUID
    project_id: UUID
    filename: str
    content_type: str | None
    size_bytes: int
    status: str
    error_code: str | None = None
    error_message: str | None = None
    source_count: int
    created_at: datetime
    updated_at: datetime
    job_id: UUID | None = None


class SourceLocatorResponse(BaseModel):
    kind: str
    page: int | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None


class SourceResponse(BaseModel):
    id: UUID
    document_id: UUID
    filename: str
    locator: SourceLocatorResponse
    text: str
