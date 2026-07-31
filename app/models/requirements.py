from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.documents import SourceLocatorResponse


RequirementType = Literal[
    "technical_requirement", "scoring_requirement",
    "commercial_requirement", "qualification_requirement",
    "delivery_requirement", "compliance_requirement",
    "format_requirement", "document_structure_requirement",
    # Transitional API compatibility; migration 020 rewrites stored values.
    "technical_capability", "functional_requirement",
    "system_architecture", "security_requirement",
    "performance_requirement", "implementation_requirement",
    "project_management", "operation_maintenance",
    "training_requirement", "other",
    "technical", "scoring", "delivery",
    "qualification", "compliance", "commercial",
]
ResponseAction = Literal[
    "write_into_proposal", "write_into_response_table",
    "compliance_commitment", "provide_attachment",
    "risk_notice", "ignore",
]
ScoringImpact = Literal[
    "score_item", "qualification_pass", "penalty_risk", "no_score"
]
RequirementPriority = Literal["P0", "P1", "P2", "P3"]
RequirementStatus = Literal["pending", "confirmed", "rejected"]
RequirementFeedback = Literal[
    "pending",
    "confirmed",
    "not_needed",
    "classification_error",
    "source_mismatch",
    "duplicate",
    "incomplete",
]
Importance = Literal["low", "medium", "high", "critical"]
ScoringRelation = Literal[
    "high_score_item", "medium_score_item", "requirement_only", "unknown"
]
ProposalRelevance = Literal["high", "medium", "low"]


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
    classification_confidence: float = 0.5
    classification_conflict: bool = False
    classification_notes: str | None = None
    scoring_relation: ScoringRelation = "unknown"
    knowledge_support_required: bool = False
    proposal_relevance: ProposalRelevance = "low"
    proposal_chapter: str | None = None
    response_action: ResponseAction = "write_into_response_table"
    proposal_mapping: str | None = None
    scoring_impact: ScoringImpact = "no_score"
    priority: RequirementPriority = "P2"
    target_chapter: str | None = None
    need_generation: bool = False
    status: RequirementStatus
    feedback: RequirementFeedback = "pending"
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
    proposal_relevance: ProposalRelevance | None = None
    proposal_chapter: str | None = Field(default=None, max_length=200)
    scoring_relation: ScoringRelation | None = None
    target_chapter: str | None = Field(default=None, max_length=200)
    need_generation: bool | None = None
    status: RequirementStatus | None = None


class RequirementFeedbackUpdate(BaseModel):
    feedback: RequirementFeedback


class RequirementStrategyUpdate(BaseModel):
    target: Literal["proposal", "compliance"]
