from fastapi import APIRouter, Request

from app.core.errors import AppError
from app.models.ontology import OntologyGraphResponse
from app.services.ontology_graph_service import OntologyGraphService
from app.services.workspace_access_service import (
    WorkspaceAccessDeniedError,
    WorkspaceAccessService,
)


router = APIRouter(prefix="/ontology", tags=["ontology"])


@router.get("/graph", response_model=OntologyGraphResponse)
def get_ontology_graph(request: Request):
    try:
        project_id = WorkspaceAccessService.current_workspace_id(request)
    except WorkspaceAccessDeniedError as exc:
        raise AppError(
            404,
            "WORKSPACE_NOT_FOUND",
            "当前会话还没有可查看的方案，请先上传招标文件。",
        ) from exc
    return OntologyGraphService().get_current_graph(project_id)
