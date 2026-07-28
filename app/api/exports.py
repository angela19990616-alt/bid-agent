from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.models.exports import ExportCreate, ExportResponse
from app.services.export_service import (
    ExportNotFoundError,
    ExportService,
    ExportValidationError,
)


router = APIRouter(
    prefix="/projects/{project_id}/exports",
    tags=["exports"],
)


def get_export_service() -> ExportService:
    return ExportService()


@router.post(
    "",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_export(
    project_id: UUID,
    payload: ExportCreate,
    service: ExportService = Depends(get_export_service),
):
    try:
        return service.create(
            project_id,
            payload.section_id,
            payload.section_version_id,
        )
    except ExportValidationError as exc:
        raise AppError(422, "EXPORT_NOT_ALLOWED", str(exc)) from exc


@router.get("/{export_id}", response_model=ExportResponse)
def get_export(
    project_id: UUID,
    export_id: UUID,
    service: ExportService = Depends(get_export_service),
):
    try:
        return service.get(project_id, export_id)
    except ExportNotFoundError as exc:
        raise AppError(
            404,
            "EXPORT_NOT_FOUND",
            "项目中不存在该导出记录。",
        ) from exc


@router.get("/{export_id}/download")
def download_export(
    project_id: UUID,
    export_id: UUID,
    service: ExportService = Depends(get_export_service),
):
    try:
        path, filename = service.download_info(project_id, export_id)
    except ExportNotFoundError as exc:
        raise AppError(
            404,
            "EXPORT_NOT_FOUND",
            "项目中不存在该导出记录。",
        ) from exc
    except ExportValidationError as exc:
        raise AppError(409, "EXPORT_NOT_READY", str(exc)) from exc
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        filename=filename,
    )
