from typing import Literal

from pydantic import BaseModel, Field


class BusinessReviewUpdate(BaseModel):
    review_key: str = Field(min_length=3, max_length=240)
    content_hash: str = Field(min_length=64, max_length=64)
    category: Literal[
        "outline",
        "format",
        "commercial_deviation",
        "scoring_evidence",
        "qualification_material",
    ]
    action: Literal["confirm", "reset", "reject"]
    note: str | None = Field(default=None, max_length=500)
