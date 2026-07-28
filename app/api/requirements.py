from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.errors import AppError
from app.models.requirements import (
    RequirementExtractRequest,
    RequirementExtractResponse,
    RequirementResponse,
    RequirementUpdate,
)
from app.services.requirement_service import (
    RequirementNotFoundError,
    RequirementService,
    RequirementValidationError,
)


router = APIRouter(
    prefix="/projects/{project_id}/requirements",
    tags=["requirements"],
)


def get_requirement_service() -> RequirementService:
    return RequirementService()


@router.post(
    "/extract",
    response_model=RequirementExtractResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def extract_requirements(
    project_id: UUID,
    payload: RequirementExtractRequest,
    service: RequirementService = Depends(get_requirement_service),
):
    try:
        created, skipped = service.extract(
            project_id,
            payload.document_ids,
        )
    except RequirementValidationError as exc:
        raise AppError(
            422,
            "REQUIREMENT_EXTRACTION_INPUT_INVALID",
            str(exc),
        ) from exc
    return RequirementExtractResponse(
        created_count=created,
        skipped_count=skipped,
    )


@router.get("", response_model=list[RequirementResponse])
def list_requirements(
    project_id: UUID,
    requirement_status: Literal[
        "pending", "confirmed", "rejected"
    ] | None = Query(default=None, alias="status"),
    requirement_type: Literal[
        "technical", "scoring", "delivery", "qualification"
    ] | None = Query(default=None, alias="type"),
    document_id: UUID | None = None,
    service: RequirementService = Depends(get_requirement_service),
):
    return service.list(
        project_id,
        status=requirement_status,
        requirement_type=requirement_type,
        document_id=document_id,
    )


@router.patch(
    "/{requirement_id}",
    response_model=RequirementResponse,
)
def update_requirement(
    project_id: UUID,
    requirement_id: UUID,
    payload: RequirementUpdate,
    service: RequirementService = Depends(get_requirement_service),
):
    try:
        return service.update(
            project_id,
            requirement_id,
            payload.model_dump(exclude_unset=True),
        )
    except RequirementNotFoundError as exc:
        raise AppError(
            404,
            "REQUIREMENT_NOT_FOUND",
            "项目中不存在该要求。",
        ) from exc
    except RequirementValidationError as exc:
        raise AppError(
            422,
            "REQUIREMENT_SOURCE_REQUIRED",
            str(exc),
        ) from exc


@router.delete(
    "/{requirement_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reject_requirement(
    project_id: UUID,
    requirement_id: UUID,
    service: RequirementService = Depends(get_requirement_service),
):
    try:
        service.reject(project_id, requirement_id)
    except RequirementNotFoundError as exc:
        raise AppError(
            404,
            "REQUIREMENT_NOT_FOUND",
            "项目中不存在该要求。",
        ) from exc
    return Response(status_code=204)
