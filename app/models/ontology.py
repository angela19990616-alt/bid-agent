from typing import Any, Literal

from pydantic import BaseModel, Field


class OntologyNodeResponse(BaseModel):
    id: str
    kind: Literal[
        "project", "organization", "document", "section", "slot",
        "role", "person", "action",
    ]
    label: str
    subtitle: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class OntologyEdgeResponse(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    label: str


class OntologyGraphResponse(BaseModel):
    title: str
    ontology_version: str
    storage: Literal["neo4j", "postgres_projection"]
    graph_status: Literal["ready", "degraded"]
    message: str
    nodes: list[OntologyNodeResponse]
    edges: list[OntologyEdgeResponse]
    summary: dict[str, int] = Field(default_factory=dict)
