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
    origin: Literal["generated", "edited", "auto_fixed"]
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
    sort_order: int = 0
    is_recommended: bool = False
    requirement_ids: list[UUID]
    current_version: SectionVersionResponse | None = None
    findings: list[ReviewFindingResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    job_id: UUID | None = None


class SectionContentUpdate(BaseModel):
    base_version_id: UUID
    content: str = Field(min_length=1, max_length=200000)


class SectionGenerationRequest(BaseModel):
    instruction: str | None = Field(default=None, max_length=1000)
