from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GenerationProfileResponse(BaseModel):
    project_id: UUID
    generation_mode: Literal[
        "strict_template", "planned", "pdf_template_manual_fill"
    ]
    historical_case_mode: Literal[
        "closest_case", "balanced", "structure_only", "current_only"
    ]
    template_descriptor: dict[str, Any] = Field(default_factory=dict)
    template_filename: str | None = None
    template_field_values: dict[str, str] = Field(default_factory=dict)


class TemplateFieldsUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
