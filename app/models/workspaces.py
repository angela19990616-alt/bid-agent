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


class ResponseSummary(BaseModel):
    total: int = 0
    proposal: int = 0
    scoring: int = 0
    compliance: int = 0
    risk: int = 0


class TemplateOutlineItem(BaseModel):
    title: str
    level: int = Field(ge=1, le=5)
    order: int = Field(ge=1)
    source: str


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
    response_summary: ResponseSummary = Field(
        default_factory=ResponseSummary
    )
    outline: list[SectionResponse] = Field(default_factory=list)
    estimated_remaining_seconds_low: int | None = None
    estimated_remaining_seconds_high: int | None = None
    estimate_sample_count: int = 0
    estimate_basis: str = "insufficient_history"
    processing_error_code: str | None = None
    processing_error_message: str | None = None
    processing_retryable: bool = False
    generation_mode: str = "planned"
    historical_case_mode: str = "closest_case"
    template_filename: str | None = None
    template_fidelity: str | None = None
    template_required_fields: list[str] = Field(default_factory=list)
    template_field_values: dict[str, str] = Field(default_factory=dict)
    template_outline: list[TemplateOutlineItem] = Field(default_factory=list)
    model_calls_used: int = 0
    model_calls_limit: int = 40
    model_tokens_used: int = 0
    model_tokens_limit: int = 300000
