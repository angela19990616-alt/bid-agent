from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


ProjectStatus = Literal[
    "draft",
    "parsing",
    "reviewing_requirements",
    "writing",
    "ready_to_export",
    "exported",
]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("项目名称不能为空")
        return clean


class ProjectResponse(BaseModel):
    id: UUID
    name: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class ProjectDetailResponse(ProjectResponse):
    document_count: int = 0
    requirement_count: int = 0
    section_count: int = 0
