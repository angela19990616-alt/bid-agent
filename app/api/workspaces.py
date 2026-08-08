from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from app.core.errors import AppError
from app.models.exports import ExportResponse
from app.models.conflicts import (
    ConflictResolutionRequest,
    ConflictResponse,
)
from app.models.requirements import (
    RequirementFeedbackUpdate,
    RequirementResponse,
    RequirementStrategyUpdate,
)
from app.models.sections import (
    SectionContentUpdate,
    SectionGenerationRequest,
    SectionResponse,
)
from app.models.workspaces import OutlineUpdate, WorkspaceResponse
from app.models.generation_profiles import (
    TemplateFieldReviewUpdate,
    TemplateFieldsUpdate,
)
from app.services.project_document_service import (
    DocumentParseFailedError,
    DuplicateDocumentError,
)
from app.services.export_service import (
    ExportNotFoundError,
    ExportService,
    ExportValidationError,
)
from app.services.conflict_service import (
    ConflictNotFoundError,
    ConflictResolutionError,
    ConflictService,
)
from app.services.project_service import ProjectNotFoundError
from app.services.proposal_plan_service import (
    ProposalPlanError,
    ProposalPlanService,
)
from app.services.proposal_review_service import ProposalReviewService
from app.services.requirement_service import (
    RequirementExtractionError,
    RequirementNotFoundError,
    RequirementService,
    RequirementValidationError,
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
from app.services.workspace_access_service import (
    SESSION_COOKIE,
    WorkspaceAccessDeniedError,
    WorkspaceAccessService,
)
from app.services.workspace_job_service import WorkspaceJobService
from app.services.response_support_service import ResponseSupportService
from app.services.generation_profile_service import GenerationProfileService
from app.config.settings import settings


router = APIRouter(prefix="/workspaces", tags=["proposal-workspaces"])


def get_workspace_service() -> WorkspaceService:
    return WorkspaceService()


def get_workspace_access_service() -> WorkspaceAccessService:
    return WorkspaceAccessService()


def get_workspace_job_service() -> WorkspaceJobService:
    return WorkspaceJobService()


def authorize_workspace(
    workspace_id: UUID,
    request: Request,
    service: WorkspaceAccessService = Depends(
        get_workspace_access_service
    ),
) -> None:
    try:
        service.authorize(workspace_id, request)
    except WorkspaceAccessDeniedError as exc:
        # Do not reveal whether a workspace exists to another session or IP.
        raise AppError(
            404,
            "WORKSPACE_NOT_FOUND",
            "当前会话无权访问该方案。",
        ) from exc


@router.post(
    "",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    service: WorkspaceService = Depends(get_workspace_service),
    access_service: WorkspaceAccessService = Depends(
        get_workspace_access_service
    ),
    job_service: WorkspaceJobService = Depends(get_workspace_job_service),
):
    filename = file.filename or "upload"
    if not filename.lower().endswith((".pdf", ".docx")):
        raise AppError(415, "DOCUMENT_UNSUPPORTED", "仅支持 PDF 或 DOCX 文件。")
    try:
        content = await file.read()
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            raise AppError(
                413,
                "DOCUMENT_TOO_LARGE",
                f"文件超过 {settings.max_upload_size_mb}MB 上限。",
            )
        access = access_service.session(request)
        if not hasattr(service, "prepare_from_upload"):
            workspace = service.create_from_upload(
                filename,
                file.content_type,
                content,
            )
        else:
            workspace, document_id, run_id = service.prepare_from_upload(
                filename,
                file.content_type,
                content,
            )
            job_service.enqueue(
                workspace["id"],
                document_id,
                run_id,
            )
        access_service.bind(workspace["id"], access)
        response.set_cookie(
            SESSION_COOKIE,
            access.token,
            httponly=True,
            secure=(
                request.headers.get("x-forwarded-proto")
                == "https"
                or request.url.scheme == "https"
            ),
            samesite="strict",
            path="/",
        )
        return workspace
    except InvalidTenderDocumentError as exc:
        raise AppError(
            422,
            "INVALID_TENDER_DOCUMENT",
            exc.reason,
            {"retryable": False},
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
    _access: None = Depends(authorize_workspace),
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        return service.get(workspace_id)
    except ProjectNotFoundError as exc:
        raise AppError(404, "WORKSPACE_NOT_FOUND", "未找到该方案。") from exc


@router.put(
    "/{workspace_id}/template-fields",
    response_model=WorkspaceResponse,
)
def update_workspace_template_fields(
    workspace_id: UUID,
    payload: TemplateFieldsUpdate,
    _access: None = Depends(authorize_workspace),
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        GenerationProfileService.update_template_fields(
            workspace_id, payload.values
        )
        return service.get(workspace_id)
    except ValueError as exc:
        raise AppError(
            422,
            "TEMPLATE_FIELDS_INVALID",
            str(exc),
        ) from exc


@router.post(
    "/{workspace_id}/template-fields/review",
    response_model=WorkspaceResponse,
)
def review_workspace_template_field(
    workspace_id: UUID,
    payload: TemplateFieldReviewUpdate,
    _access: None = Depends(authorize_workspace),
    service: WorkspaceService = Depends(get_workspace_service),
):
    try:
        GenerationProfileService.review_template_field(
            workspace_id,
            payload.field_key,
            payload.action,
        )
        return service.get(workspace_id)
    except ValueError as exc:
        raise AppError(
            422,
            "TEMPLATE_FIELD_REVIEW_INVALID",
            str(exc),
        ) from exc


@router.post(
    "/{workspace_id}/retry",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_workspace(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
    service: WorkspaceService = Depends(get_workspace_service),
    job_service: WorkspaceJobService = Depends(get_workspace_job_service),
):
    try:
        workspace, document_id, run_id = service.prepare_retry(workspace_id)
        job_service.enqueue(
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
    view: Literal[
        "all", "proposal", "scoring", "compliance", "risk"
    ] = "all",
    _access: None = Depends(authorize_workspace),
):
    items = RequirementService().list(workspace_id)
    if view == "proposal":
        return [
            item for item in items
            if item["response_action"] == "write_into_proposal"
        ]
    if view == "scoring":
        return [
            item for item in items
            if item["scoring_impact"] == "score_item"
        ]
    if view == "compliance":
        return [
            item for item in items
            if item["type"] in {
                "commercial_requirement",
                "qualification_requirement",
                "compliance_requirement",
                "format_requirement",
                "document_structure_requirement",
            }
        ]
    if view == "risk":
        return [
            item for item in items
            if item["scoring_impact"] == "penalty_risk"
            or item["response_action"] == "risk_notice"
        ]
    return items


@router.get("/{workspace_id}/response-support")
def get_workspace_response_support(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    return ResponseSupportService().overview(workspace_id)


@router.get(
    "/{workspace_id}/conflicts",
    response_model=list[ConflictResponse],
)
def list_workspace_conflicts(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    return ConflictService().list(workspace_id)


@router.patch(
    "/{workspace_id}/conflicts/{conflict_id}",
    response_model=ConflictResponse,
)
def resolve_workspace_conflict(
    workspace_id: UUID,
    conflict_id: UUID,
    payload: ConflictResolutionRequest,
    _access: None = Depends(authorize_workspace),
):
    try:
        return ConflictService().resolve(
            workspace_id,
            conflict_id,
            choice=payload.choice,
            resolved_by=payload.resolved_by,
            note=payload.note,
        )
    except ConflictNotFoundError as exc:
        raise AppError(404, "CONFLICT_NOT_FOUND", "未找到该冲突事项。") from exc


@router.patch(
    "/{workspace_id}/requirements/{requirement_id}/feedback",
    response_model=RequirementResponse,
)
def record_workspace_requirement_feedback(
    workspace_id: UUID,
    requirement_id: UUID,
    payload: RequirementFeedbackUpdate,
    _access: None = Depends(authorize_workspace),
):
    try:
        requirement = RequirementService().record_feedback(
            workspace_id,
            requirement_id,
            payload.feedback,
        )
        ProposalPlanService().reconcile_requirement_feedback(
            workspace_id,
            requirement_id,
        )
        return requirement
    except RequirementNotFoundError as exc:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "未找到该要求。") from exc
    except RequirementValidationError as exc:
        raise AppError(422, "REQUIREMENT_FEEDBACK_INVALID", str(exc)) from exc


@router.patch(
    "/{workspace_id}/requirements/{requirement_id}/strategy",
    response_model=RequirementResponse,
)
def update_workspace_requirement_strategy(
    workspace_id: UUID,
    requirement_id: UUID,
    payload: RequirementStrategyUpdate,
    _access: None = Depends(authorize_workspace),
):
    try:
        requirement = RequirementService().update_response_strategy(
            workspace_id,
            requirement_id,
            payload.target,
        )
        ProposalPlanService().reconcile_requirement_feedback(
            workspace_id,
            requirement_id,
        )
        return requirement
    except RequirementNotFoundError as exc:
        raise AppError(404, "REQUIREMENT_NOT_FOUND", "未找到该要求。") from exc
    except RequirementValidationError as exc:
        raise AppError(
            422,
            "RESPONSE_STRATEGY_INVALID",
            str(exc),
        ) from exc


@router.put(
    "/{workspace_id}/outline",
    response_model=list[SectionResponse],
)
def replace_outline(
    workspace_id: UUID,
    payload: OutlineUpdate,
    _access: None = Depends(authorize_workspace),
):
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
def generate_section(
    workspace_id: UUID,
    section_id: UUID,
    payload: SectionGenerationRequest | None = None,
    _access: None = Depends(authorize_workspace),
):
    try:
        ConflictService.assert_section_unblocked(workspace_id, section_id)
        return SectionService().generate(
            workspace_id,
            section_id,
            payload.instruction if payload else None,
            payload.case_reference_mode if payload else "balanced",
            payload.min_chars if payload else 800,
            payload.max_chars if payload else 5000,
        )
    except SectionNotFoundError as exc:
        raise AppError(404, "SECTION_NOT_FOUND", "未找到该章节。") from exc
    except SectionValidationError as exc:
        raise AppError(422, "SECTION_INVALID", str(exc)) from exc
    except ConflictResolutionError as exc:
        raise AppError(409, "SECTION_CONFLICT_PENDING", str(exc)) from exc
    except SectionGenerationError as exc:
        raise AppError(
            502,
            "SECTION_GENERATION_FAILED",
            str(exc),
            {"job_id": str(exc.job_id), "retryable": True},
        ) from exc


@router.post(
    "/{workspace_id}/generate-draft",
    response_model=WorkspaceResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_complete_draft(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    sections = SectionService().list(workspace_id)
    if not sections:
        raise AppError(422, "OUTLINE_REQUIRED", "请先确认方案目录。")
    WorkspaceJobService().enqueue_autonomous_draft(workspace_id)
    return WorkspaceService().get(workspace_id)


@router.put(
    "/{workspace_id}/sections/{section_id}/content",
    response_model=SectionResponse,
)
def save_section(
    workspace_id: UUID,
    section_id: UUID,
    payload: SectionContentUpdate,
    _access: None = Depends(authorize_workspace),
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
def approve_section(
    workspace_id: UUID,
    section_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    try:
        return SectionService().approve(workspace_id, section_id)
    except (SectionNotFoundError, SectionValidationError) as exc:
        raise AppError(422, "SECTION_APPROVAL_FAILED", str(exc)) from exc


@router.post(
    "/{workspace_id}/exports",
    response_model=ExportResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def export_full_proposal(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    try:
        ConflictService.assert_export_ready(workspace_id)
        return ExportService().create_full(workspace_id)
    except ExportValidationError as exc:
        raise AppError(422, "EXPORT_NOT_ALLOWED", str(exc)) from exc
    except ConflictResolutionError as exc:
        raise AppError(409, "CONFLICT_PENDING", str(exc)) from exc


@router.get("/{workspace_id}/review")
def get_proposal_review(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    try:
        return ProposalReviewService().latest(workspace_id)
    except ValueError as exc:
        raise AppError(404, "REVIEW_NOT_FOUND", str(exc)) from exc


@router.post("/{workspace_id}/review")
def run_proposal_review(
    workspace_id: UUID,
    _access: None = Depends(authorize_workspace),
):
    try:
        return ProposalReviewService().prepare_for_export(workspace_id)
    except ValueError as exc:
        raise AppError(422, "REVIEW_FAILED", str(exc)) from exc


@router.get("/{workspace_id}/review/download")
def download_proposal_review(
    workspace_id: UUID,
    format: Literal["json", "md"] = "md",
    _access: None = Depends(authorize_workspace),
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
def download_full_proposal(
    workspace_id: UUID,
    export_id: UUID,
    _access: None = Depends(authorize_workspace),
):
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
