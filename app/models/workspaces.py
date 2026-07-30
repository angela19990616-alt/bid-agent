from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.documents import ProjectDocumentResponse
from app.models.requirements import RequirementResponse
from app.models.sections import SectionResponse


class OutlineChapterUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    requirement_ids: list[UUID] = Field(min_length=1, max_length=100)


class OutlineUpdate(BaseModel):
    chapters: list[OutlineChapterUpdate] = Field(min_length=1, max_length=30)


class WorkspaceResponse(BaseModel):
    id: UUID
    name: str
    status: str
    created_at: datetime
    updated_at: datetime
    document: ProjectDocumentResponse | None = None
    technical_requirements: list[RequirementResponse] = Field(
        default_factory=list
    )
    compliance_reminder_count: int = 0
    outline: list[SectionResponse] = Field(default_factory=list)
    estimated_remaining_seconds_low: int | None = None
    estimated_remaining_seconds_high: int | None = None
    estimate_sample_count: int = 0
    estimate_basis: str = "insufficient_history"
    model_calls_used: int = 0
    model_calls_limit: int = 12
    model_tokens_used: int = 0
    model_tokens_limit: int = 80000
