from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


RuleType = Literal[
    "extraction", "classification", "response_strategy", "knowledge",
    "proposal_memory", "writing", "compliance", "conflict_detection",
    "response_prioritization", "template_generation", "entity_relation",
]


class RuleCreate(BaseModel):
    rule_type: RuleType
    name: str = Field(min_length=2, max_length=200)
    content: dict[str, Any]
    source: Literal["manual", "ai_generated"] = "manual"
    activate: bool = False


class RuleResponse(BaseModel):
    definition_id: UUID | None = None
    rule_type: RuleType
    rule_key: str
    name: str
    version: int
    content: dict[str, Any]
    checksum: str
    source: str


class KnowledgeCreate(BaseModel):
    category: Literal[
        "company_profile",
        "qualification",
        "product_capability",
        "technical_capability",
        "case_study",
        "standard_template",
        "expert_experience",
        "historical_bid",
        "common_chapter",
    ]
    title: str = Field(min_length=2, max_length=300)
    content: str = Field(min_length=10, max_length=200000)
    metadata: dict[str, Any] = Field(default_factory=dict)
