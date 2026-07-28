from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.documents import SourceLocatorResponse


RequirementType = Literal[
    "technical",
    "scoring",
    "delivery",
    "qualification",
    "compliance",
    "commercial",
]
RequirementStatus = Literal["pending", "confirmed", "rejected"]
Importance = Literal["low", "medium", "high"]


class RequirementSourceResponse(BaseModel):
    id: UUID
    document_id: UUID
    filename: str
    locator: SourceLocatorResponse


class RequirementResponse(BaseModel):
    id: UUID
    project_id: UUID
    type: RequirementType
    title: str
    normalized_text: str
    quote: str
    importance: Importance
    confidence: float
    status: RequirementStatus
    sources: list[RequirementSourceResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RequirementExtractRequest(BaseModel):
    document_ids: list[UUID] = Field(min_length=1, max_length=20)


class RequirementExtractResponse(BaseModel):
    created_count: int
    skipped_count: int


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    normalized_text: str | None = Field(
        default=None,
        min_length=1,
        max_length=4000,
    )
    type: RequirementType | None = None
    importance: Importance | None = None
    status: RequirementStatus | None = None
