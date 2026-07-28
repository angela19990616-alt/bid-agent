from pydantic import BaseModel, Field

from app.models.documents import SearchResultResponse


class GenerateRequest(BaseModel):
    query: str = Field(min_length=2, max_length=8000)
    retrieval_limit: int = Field(default=5, ge=1, le=20)


class GenerateResponse(BaseModel):
    query: str
    analysis: str
    answer: str
    sources: list[SearchResultResponse] = Field(default_factory=list)

