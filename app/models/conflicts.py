from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ConflictResponse(BaseModel):
    conflict_id: UUID
    topic: str
    conflict_type: Literal[
        "positive_difference", "compatible_difference",
        "potential_conflict", "true_conflict",
    ]
    source_a: dict[str, Any]
    source_b: dict[str, Any]
    source_a_location: dict[str, Any]
    source_b_location: dict[str, Any]
    source_a_authority_level: int
    source_b_authority_level: int
    description: str
    risk_priority: Literal["P0", "P1", "P2", "P3"]
    resolution_status: Literal["pending", "resolved", "ignored"]
    resolution_choice: Literal[
        "choose_a", "choose_b", "keep_both", "request_clarification"
    ] | None = None
    resolved_by: str | None = None
    resolved_time: datetime | None = None
    affected_sections: list[str] = Field(default_factory=list)


class ConflictResolutionRequest(BaseModel):
    choice: Literal[
        "choose_a", "choose_b", "keep_both", "request_clarification"
    ]
    resolved_by: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)
