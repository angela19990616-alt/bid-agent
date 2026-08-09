from uuid import UUID

from fastapi import APIRouter, Depends, File, UploadFile, status

from app.config.settings import settings
from app.core.errors import AppError
from app.models.documents import (
    ProjectDocumentResponse,
    SourceLocatorResponse,
    SourceResponse,
)
from app.services.project_document_service import (
    DocumentParseFailedError,
    DuplicateDocumentError,
    ProjectDocumentNotFoundError,
    ProjectDocumentService,
)


router = APIRouter(prefix="/projects/{project_id}", tags=["project documents"])


def get_project_document_service() -> ProjectDocumentService:
    return ProjectDocumentService()


@router.post(
    "/documents",
    response_model=ProjectDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_project_document(
    project_id: UUID,
    file: UploadFile = File(...),
    service: ProjectDocumentService = Depends(get_project_document_service),
):
    content = await file.read()
    maximum = settings.max_upload_size_mb * 1024 * 1024
    if len(content) > maximum:
        raise AppError(
            status_code=413,
            code="DOCUMENT_TOO_LARGE",
            message=f"文件不能超过 {settings.max_upload_size_mb} MB。",
        )
    try:
        return service.upload_and_parse(
            project_id,
            file.filename or "unnamed",
            file.content_type,
            content,
        )
    except ProjectDocumentNotFoundError as exc:
        raise AppError(404, "PROJECT_NOT_FOUND", "项目不存在。") from exc
    except DuplicateDocumentError as exc:
        raise AppError(
            409,
            "DOCUMENT_DUPLICATE",
            "该项目已上传相同文件。",
        ) from exc
    except DocumentParseFailedError as exc:
        raise AppError(
            400,
            exc.code,
            exc.message,
            {
                "document_id": str(exc.document_id),
                "job_id": str(exc.job_id),
                "retryable": True,
            },
        ) from exc


@router.get(
    "/documents",
    response_model=list[ProjectDocumentResponse],
)
def list_project_documents(
    project_id: UUID,
    service: ProjectDocumentService = Depends(get_project_document_service),
):
    return service.list(project_id)


@router.get(
    "/documents/{document_id}",
    response_model=ProjectDocumentResponse,
)
def get_project_document(
    project_id: UUID,
    document_id: UUID,
    service: ProjectDocumentService = Depends(get_project_document_service),
):
    try:
        return service.get(project_id, document_id)
    except ProjectDocumentNotFoundError as exc:
        raise AppError(
            404,
            "DOCUMENT_NOT_FOUND",
            "项目中不存在该文件。",
        ) from exc


@router.post(
    "/documents/{document_id}/parse",
    response_model=ProjectDocumentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_project_document_parse(
    project_id: UUID,
    document_id: UUID,
    service: ProjectDocumentService = Depends(get_project_document_service),
):
    try:
        return service.retry_parse(project_id, document_id)
    except ProjectDocumentNotFoundError as exc:
        raise AppError(
            404,
            "DOCUMENT_NOT_RETRYABLE",
            "文件不存在或当前状态不允许重试。",
        ) from exc
    except DocumentParseFailedError as exc:
        raise AppError(
            400,
            exc.code,
            exc.message,
            {
                "document_id": str(exc.document_id),
                "job_id": str(exc.job_id),
                "retryable": True,
            },
        ) from exc


@router.get("/sources/{source_id}", response_model=SourceResponse)
def get_source(
    project_id: UUID,
    source_id: UUID,
    service: ProjectDocumentService = Depends(get_project_document_service),
):
    try:
        source = service.get_source(project_id, source_id)
    except ProjectDocumentNotFoundError as exc:
        raise AppError(
            404,
            "SOURCE_NOT_FOUND",
            "项目中不存在该来源片段。",
        ) from exc
    return SourceResponse(
        id=source.id,
        document_id=source.document_id,
        filename=source.filename,
        locator=SourceLocatorResponse(
            kind=source.locator_kind,
            page=source.page_no,
            paragraph_start=source.paragraph_start,
            paragraph_end=source.paragraph_end,
        ),
        text=source.text,
    )
