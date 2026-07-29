from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.models.exports import ExportResponse
from app.models.requirements import RequirementResponse
from app.models.sections import SectionContentUpdate, SectionResponse
from app.models.workspaces import OutlineUpdate, WorkspaceResponse
from app.services.project_document_service import (
    DocumentParseFailedError,
    DuplicateDocumentError,
)
from app.services.export_service import (
    ExportNotFoundError,
    ExportService,
    ExportValidationError,
)
from app.services.project_service import ProjectNotFoundError
from app.services.proposal_plan_service import (
    ProposalPlanError,
    ProposalPlanService,
)
from app.services.proposal_review_service import ProposalReviewService
from app.services.requirement_service import (
    RequirementExtractionError,
    RequirementService,
)
from app.services.section_service import (
    SectionGenerationError,
    SectionNotFoundError,
    SectionService,
    SectionValidationError,
    SectionVersionConflictError,
)
from app.services.workspace_service import (
    InvalidTenderDocumentError,
    WorkspaceRetryError,
    WorkspaceService,
)


router = APIRouter(prefix="/workspaces", tags=["proposal-workspaces"])


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService()


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    service: WorkspaceService = Depends(get_workspace_service),
):
    filename = file.filename or "upload"
    if not filename.lower().endswith((".pdf", ".docx")):
        raise AppError(415, "DOCUMENT_UNSUPPORTED", "仅支持 PDF 或 DOCX 文件。")
    try:
        content = await file.read()
        if not hasattr(service, "prepare_from_upload"):
            return service.create_from_upload(
                filename,
                file.content_type,
                content,
            )
        workspace, document_id, run_id = service.prepare_from_upload(
            filename,
            file.content_type,
            content,
        )
        background_tasks.add_task(
            service.complete_prepared_upload,
            workspace["id"],
            document_id,
            run_id,
        )
        return workspace
    except InvalidTenderDocumentError as exc:
        raise AppError(
            422,
            "INVALID_TENDER_DOCUMENT",
            exc.reason,
            {"workspace_id": str(exc.workspace_id)},
        ) from exc
    except DuplicateDocumentError as exc:
        raise AppError(409, "DOCUMENT_DUPLICATE", "该文件已经上传过。") from exc
    except DocumentParseFailedError as exc:
        raise AppError(422, exc.code, exc.message) from exc
    except RequirementExtractionError as exc:
        raise AppError(
            502,
            "REQUIREMENT_AGENT_FAILED",
            str(exc),
            {"retryable": True},
        ) from exc
    except ProposalPlanError as exc:
        raise AppError(422, "PROPOSAL_PLAN_EMPTY", str(exc)) from exc


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
def get_workspace(
    workspace_id: UUID,
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        return service.get(workspace_id)
    except ProjectNotFoundError as exc:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "未找到该方案。") from exc


@router.get("/recent/latest", response_model=WorkspaceResponse)
def get_latest_workspace(
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        return service.get_latest()
    except ProjectNotFoundError as exc:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "暂时没有可恢复的方案。") from exc


@router.post(
    "/{workspace_id}/retry",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_workspace(
    workspace_id: UUID,
    background_tasks: BackgroundTasks,
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        workspace, document_id, run_id = service.prepare_retry(workspace_id)
        background_tasks.add_task(
            service.complete_prepared_upload,
            workspace_id,
            document_id,
            run_id,
        )
        return workspace
    except ProjectNotFoundError as exc:
        raise AppError(
            404,
            "WORKSPACE_NOT_FOUND",
            "未找到该方案。",
        ) from exc
    except WorkspaceRetryError as exc:
        raise AppError(
            409,
            "WORKSPACE_NOT_RETRYABLE",
            str(exc),
        ) from exc


@router.get(
    "/{workspace_id}/requirements",
    response_model=list[RequirementResponse],
)
def list_workspace_requirements(
    workspace_id: UUID,
    view: Literal["proposal", "compliance"] = "proposal",
):
    return RequirementService().list(
        workspace_id,
        need_generation=view == "proposal",
    )


@router.put(
    "/{workspace_id}/outline",
    response_model=list[SectionResponse],
)
def replace_outline(workspace_id: UUID, payload: OutlineUpdate):
    try:
        return ProposalPlanService().replace_outline(
            workspace_id,
            [item.model_dump() for item in payload.chapters],
        )
    except ProposalPlanError as exc:
        raise AppError(422, "OUTLINE_INVALID", str(exc)) from exc


@router.post(
    "/{workspace_id}/sections/{section_id}/generate",
    response_model=SectionResponse,
)
def generate_section(workspace_id: UUID, section_id: UUID):
    try:
        return SectionService().generate(workspace_id, section_id)
    except SectionNotFoundError as exc:
        raise AppError(404, "SECTION_NOT_FOUND", "未找到该章节。") from exc
    except SectionValidationError as exc:
        raise AppError(422, "SECTION_INVALID", str(exc)) from exc
    except SectionGenerationError as exc:
        raise AppError(
            502,
            "SECTION_GENERATION_FAILED",
            str(exc),
            {"job_id": str(exc.job_id), "retryable": True},
        ) from exc


@router.put(
    "/{workspace_id}/sections/{section_id}/content",
    response_model=SectionResponse,
)
def save_section(
    workspace_id: UUID,
    section_id: UUID,
    payload: SectionContentUpdate,
):
    try:
        return SectionService().save_content(
            workspace_id,
            section_id,
            payload.base_version_id,
            payload.content,
        )
    except SectionNotFoundError as exc:
        raise AppError(404, "SECTION_NOT_FOUND", "未找到该章节。") from exc
    except SectionVersionConflictError as exc:
        raise AppError(
            409,
            "SECTION_VERSION_CONFLICT",
            "章节已被更新，请刷新后再保存。",
        ) from exc


@router.post(
    "/{workspace_id}/sections/{section_id}/approve",
    response_model=SectionResponse,
)
def approve_section(workspace_id: UUID, section_id: UUID):
    try:
        return SectionService().approve(workspace_id, section_id)
    except (SectionNotFoundError, SectionValidationError) as exc:
        raise AppError(422, "SECTION_APPROVAL_FAILED", str(exc)) from exc


@router.post(
    "/{workspace_id}/exports",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_full_proposal(workspace_id: UUID):
    try:
        return ExportService().create_full(workspace_id)
    except ExportValidationError as exc:
        raise AppError(422, "EXPORT_NOT_ALLOWED", str(exc)) from exc


@router.get("/{workspace_id}/review")
def get_proposal_review(workspace_id: UUID):
    try:
        return ProposalReviewService().latest(workspace_id)
    except ValueError as exc:
        raise AppError(404, "REVIEW_NOT_FOUND", str(exc)) from exc


@router.post("/{workspace_id}/review")
def run_proposal_review(workspace_id: UUID):
    try:
        return ProposalReviewService().prepare_for_export(
            workspace_id, enforce=False
        )
    except ValueError as exc:
        raise AppError(422, "REVIEW_FAILED", str(exc)) from exc


@router.get("/{workspace_id}/review/download")
def download_proposal_review(
    workspace_id: UUID,
    format: Literal["json", "md"] = "md",
):
    try:
        json_path, markdown_path = ProposalReviewService().report_files(
            workspace_id
        )
    except ValueError as exc:
        raise AppError(404, "REVIEW_NOT_FOUND", str(exc)) from exc
    path = json_path if format == "json" else markdown_path
    return FileResponse(
        path,
        media_type=(
            "application/json"
            if format == "json"
            else "text/markdown; charset=utf-8"
        ),
        filename=(
            "proposal_review.json"
            if format == "json"
            else "Proposal_Review.md"
        ),
    )


@router.get("/{workspace_id}/exports/{export_id}/download")
def download_full_proposal(workspace_id: UUID, export_id: UUID):
    try:
        path, filename = ExportService().download_info(
            workspace_id, export_id
        )
    except ExportNotFoundError as exc:
        raise AppError(404, "EXPORT_NOT_FOUND", "导出记录不存在。") from exc
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
