from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GenerationProfileResponse(BaseModel):
    project_id: UUID
    generation_mode: Literal[
        "strict_template", "planned", "pdf_template_manual_fill",
        "template_conversion_required",
    ]
    writer_strategy: Literal[
        "strict_template_writer", "planned_proposal_writer"
    ] | None = None
    template_conversion_status: str = "not_required"
    template_conversion_report: dict[str, Any] = Field(default_factory=dict)
    historical_case_mode: Literal[
        "closest_case", "balanced", "structure_only", "current_only"
    ]
    template_descriptor: dict[str, Any] = Field(default_factory=dict)
    template_filename: str | None = None
    template_field_values: dict[str, str] = Field(default_factory=dict)


class TemplateFieldsUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class TemplateFieldReviewUpdate(BaseModel):
    field_key: str = Field(min_length=1, max_length=80)
    action: Literal["confirm", "reset"]
    value: str | None = Field(default=None, min_length=1, max_length=500)


class RoleBindingUpdate(BaseModel):
    role: Literal[
        "LEGAL_REPRESENTATIVE", "AUTHORIZED_REPRESENTATIVE",
        "PROJECT_MANAGER", "TECHNICAL_LEAD", "CONTACT_PERSON",
        "SIGNATORY",
    ]
    person_id: UUID


class TemplateFieldDecisionResponse(BaseModel):
    field_key: str
    canonical_key: str
    label: str
    expected_value_type: str = "text"
    expected_value_type_label: str = "文本"
    type_validation: Literal["passed", "missing"] = "missing"
    value: str | None = None
    source_type: str | None = None
    source_reference: str | None = None
    confidence: float = Field(ge=0, le=1)
    status: Literal["AUTO_FILL", "REVIEW_REQUIRED", "MISSING"]
    reason: str
    required: bool = True
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None
    evidence_match_count: int = 0
    evidence_alternatives: list[str] = Field(default_factory=list)
    slot: dict[str, Any] = Field(default_factory=dict)
    semantic_field: str | None = None
    expected_entity_type: str | None = None
    expected_role: str | None = None
    expected_role_label: str | None = None
    subject_organization: str | None = None
    project_name: str | None = None
    binding_status: str | None = None
    match_path: list[str] = Field(default_factory=list)
    entity_candidates: list[dict[str, Any]] = Field(default_factory=list)
