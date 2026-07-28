from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.core.errors import AppError
from app.models.sections import (
    SectionContentUpdate,
    SectionCreate,
    SectionResponse,
)
from app.services.section_service import (
    SectionGenerationError,
    SectionNotFoundError,
    SectionService,
    SectionValidationError,
    SectionVersionConflictError,
)


router = APIRouter(
    prefix="/projects/{project_id}/sections",
    tags=["sections"],
)


def get_section_service() -> SectionService:
    return SectionService()


@router.post(
    "",
    response_model=SectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_section(
    project_id: UUID,
    payload: SectionCreate,
    service: SectionService = Depends(get_section_service),
):
    try:
        return service.create(
            project_id,
            payload.title,
            payload.requirement_ids,
        )
    except SectionValidationError as exc:
        raise AppError(
            422,
            "SECTION_REQUIREMENTS_INVALID",
            str(exc),
        ) from exc


@router.get("", response_model=list[SectionResponse])
def list_sections(
    project_id: UUID,
    service: SectionService = Depends(get_section_service),
):
    return service.list(project_id)


@router.post(
    "/{section_id}/generate",
    response_model=SectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_section(
    project_id: UUID,
    section_id: UUID,
    service: SectionService = Depends(get_section_service),
):
    try:
        return service.generate(project_id, section_id)
    except SectionNotFoundError as exc:
        raise AppError(
            404,
            "SECTION_NOT_FOUND",
            "项目中不存在该章节。",
        ) from exc
    except SectionValidationError as exc:
        raise AppError(422, "SECTION_NOT_GENERATABLE", str(exc)) from exc
    except SectionGenerationError as exc:
        raise AppError(
            503,
            "SECTION_GENERATION_FAILED",
            str(exc),
            {"job_id": str(exc.job_id), "retryable": True},
        ) from exc


@router.get("/{section_id}", response_model=SectionResponse)
def get_section(
    project_id: UUID,
    section_id: UUID,
    service: SectionService = Depends(get_section_service),
):
    try:
        return service.get(project_id, section_id)
    except SectionNotFoundError as exc:
        raise AppError(
            404,
            "SECTION_NOT_FOUND",
            "项目中不存在该章节。",
        ) from exc


@router.put(
    "/{section_id}/content",
    response_model=SectionResponse,
)
def save_section_content(
    project_id: UUID,
    section_id: UUID,
    payload: SectionContentUpdate,
    service: SectionService = Depends(get_section_service),
):
    try:
        return service.save_content(
            project_id,
            section_id,
            payload.base_version_id,
            payload.content,
        )
    except SectionNotFoundError as exc:
        raise AppError(
            404,
            "SECTION_NOT_FOUND",
            "项目中不存在该章节。",
        ) from exc
    except SectionVersionConflictError as exc:
        raise AppError(
            409,
            "SECTION_VERSION_CONFLICT",
            "章节已产生新版本，请刷新后再编辑。",
        ) from exc


@router.post(
    "/{section_id}/approve",
    response_model=SectionResponse,
)
def approve_section(
    project_id: UUID,
    section_id: UUID,
    service: SectionService = Depends(get_section_service),
):
    try:
        return service.approve(project_id, section_id)
    except SectionNotFoundError as exc:
        raise AppError(
            404,
            "SECTION_NOT_FOUND",
            "项目中不存在该章节。",
        ) from exc
    except SectionValidationError as exc:
        raise AppError(409, "SECTION_REVIEW_BLOCKED", str(exc)) from exc
