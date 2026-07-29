from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class ExportCreate(BaseModel):
    section_id: UUID | None
    section_version_id: UUID | None
    format: Literal["docx"] = "docx"


class ExportResponse(BaseModel):
    id: UUID
    project_id: UUID
    section_id: UUID | None = None
    section_version_id: UUID | None = None
    export_scope: Literal["section", "full_proposal"] = "section"
    format: Literal["docx"]
    status: str
    filename: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
