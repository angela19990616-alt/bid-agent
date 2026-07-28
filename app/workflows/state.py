from typing import NotRequired, TypedDict

from app.database.vector_store import SearchResult


class AgentState(TypedDict):
    query: str
    analysis: str
    retrieval: str
    answer: str
    retrieval_limit: NotRequired[int]
    sources: NotRequired[list[SearchResult]]
