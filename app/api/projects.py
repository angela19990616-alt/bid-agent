from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.errors import AppError
from app.models.projects import (
    ProjectCreate,
    ProjectDetailResponse,
    ProjectResponse,
)
from app.services.project_service import ProjectNotFoundError, ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])


def get_project_service() -> ProjectService:
    return ProjectService()


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    payload: ProjectCreate,
    service: ProjectService = Depends(get_project_service),
):
    return service.create(payload.name)


@router.get("", response_model=list[ProjectResponse])
def list_projects(service: ProjectService = Depends(get_project_service)):
    return service.list()


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: UUID,
    service: ProjectService = Depends(get_project_service),
):
    try:
        return service.get(project_id)
    except ProjectNotFoundError as exc:
        raise AppError(
            status_code=404,
            code="PROJECT_NOT_FOUND",
            message="项目不存在。",
        ) from exc
