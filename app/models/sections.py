from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class SectionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    requirement_ids: list[UUID] = Field(min_length=1, max_length=100)


class SectionVersionResponse(BaseModel):
    id: UUID
    version_no: int
    content: str
    origin: Literal["generated", "edited"]
    created_at: datetime


class ReviewFindingResponse(BaseModel):
    id: UUID
    type: str
    severity: Literal["info", "warning", "blocking"]
    message: str


class SectionResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    status: str
    requirement_ids: list[UUID]
    current_version: SectionVersionResponse | None = None
    findings: list[ReviewFindingResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    job_id: UUID | None = None


class SectionContentUpdate(BaseModel):
    base_version_id: UUID
    content: str = Field(min_length=1, max_length=200000)
