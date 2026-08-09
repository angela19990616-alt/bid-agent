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


class TemplateVariableReviewUpdate(BaseModel):
    variable_key: str = Field(min_length=1, max_length=200)
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
    ontology_concept: str = "unmapped"
    display_name: str = "待识别字段"
    subject_role: str | None = None
    relation_path: list[str] = Field(default_factory=list)
    value_expression: str | None = None
    fill_strategy: str = "unresolved"
    required_actions: list[str] = Field(default_factory=list)
    variable_key: str | None = None
    variable_standard_name: str | None = None
    variable_slot_count: int = 1


class TemplateVariableSlotResponse(BaseModel):
    field_key: str
    label: str | None = None
    display_name: str | None = None
    source_location: str
    document_section: str | None = None
    table_index: int | None = None
    paragraph_index: int | None = None
    row: int | None = None
    column: int | None = None
    surrounding_text: str | None = None


class TemplateVariableDecisionResponse(BaseModel):
    variable_key: str
    dictionary_version: str
    standard_name: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    semantic_field: str
    target_entity_type: str | None = None
    target_relation: str | None = None
    target_relations: list[str] = Field(default_factory=list)
    entity_scope_label: str = "待确认业务对象"
    expected_value_type: str
    expected_value_type_label: str = "文本"
    source_priority: list[str] = Field(default_factory=list)
    value: str | None = None
    status: Literal["AUTO_FILL", "REVIEW_REQUIRED", "MISSING"]
    reason: str
    confidence: float = Field(ge=0, le=1)
    required: bool = True
    slot_count: int = Field(ge=1)
    affected_locations: list[str] = Field(default_factory=list)
    slots: list[TemplateVariableSlotResponse] = Field(default_factory=list)
    source_type: str | None = None
    source_reference: str | None = None
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None
    evidence_match_count: int = 0
    evidence_alternatives: list[str] = Field(default_factory=list)
    binding_status: str | None = None
    relation_path: list[str] = Field(default_factory=list)
    entity_candidates: list[dict[str, Any]] = Field(default_factory=list)
    fill_strategy: str = "unresolved"
    personnel_rule_results: list[dict[str, Any]] = Field(default_factory=list)
    semantics_recognized: bool = True
    resolution_state: Literal[
        "resolved",
        "review_required",
        "enterprise_fact_pending",
        "project_fact_pending",
        "person_binding_pending",
        "person_fact_pending",
        "response_generation_pending",
        "knowledge_match_pending",
        "layout_managed",
        "semantic_review_required",
        "value_resolution_pending",
    ] = "value_resolution_pending"
    resolution_label: str = "待匹配对应资料"
    next_action: str = "系统将继续从当前项目可用资料中匹配。"
    review_group_key: str
    review_group_label: str
