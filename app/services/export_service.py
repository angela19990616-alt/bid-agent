from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from app.config.settings import settings
from app.database.db import connect
from app.services.docx_builder import (
    build_full_proposal_docx,
    build_proposal_docx,
    delivery_title,
)
from app.services.proposal_review_service import (
    ProposalReviewService,
)
from app.services.generation_profile_service import GenerationProfileService
from app.knowledge.enterprise_fact_resolver import EnterpriseFactResolver
from app.knowledge.case_fact_resolver import CaseFactResolver
from app.services.response_template_service import ResponseTemplateService
from app.services.section_service import SectionService
from app.services.entity_resolution_service import EntityResolutionService
from app.services.bid_readiness_service import BidReadinessError
from app.services.response_support_service import ResponseSupportService
from app.workflows.controlled_pipeline import ControlledPipeline


class ExportNotFoundError(Exception):
    pass


class ExportValidationError(Exception):
    pass


class ExportService:
    def create_template_preview(self, project_id: UUID) -> Path:
        """Build a disposable DOCX preview without creating a delivery record."""
        profile_service = GenerationProfileService()
        profile = profile_service.get(project_id)
        if profile.generation_mode != "strict_template":
            raise ExportValidationError("当前方案未使用原投标文件格式。")
        template_path = profile_service.template_path(profile)
        if template_path is None or not template_path.is_file():
            raise ExportValidationError("响应模板原文件不存在。")
        data = self._load_full_export_input(
            project_id,
            allow_empty_sections=True,
            allow_draft_sections=True,
        )
        decisions = profile_service.template_field_decisions(
            profile,
            {"project_name": data["project_name"]},
            EnterpriseFactResolver().resolve(project_id),
            CaseFactResolver().resolve(project_id),
            EntityResolutionService().resolve_project(project_id),
        )
        preview_values = {
            item["field_key"]: item["value"]
            for item in decisions
            if item["status"] != "MISSING" and item["value"]
        }
        destination = self.resolve_path(f"{project_id}/strict-fill-preview.docx")
        temporary = destination.with_name(
            f"strict-fill-preview-{uuid4().hex}.tmp"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            ResponseTemplateService().fill_docx(
                template_content=template_path.read_bytes(),
                output_path=temporary,
                descriptor=profile.template_descriptor,
                field_values=preview_values,
                sections=data["sections"],
                document_title=delivery_title(data["project_name"]),
            )
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise ExportValidationError("Word 审阅稿预览生成失败。") from exc
        return destination

    def create_full(self, project_id: UUID) -> dict:
        try:
            ResponseSupportService().assert_delivery_ready(project_id)
        except BidReadinessError as exc:
            raise ExportValidationError(str(exc)) from exc
        profile_service = GenerationProfileService()
        profile = profile_service.get(project_id)
        field_only_template = (
            profile.generation_mode == "strict_template"
            and not SectionService().list(project_id)
        )
        if not field_only_template:
            review = ProposalReviewService().prepare_for_export(project_id)
            if not review["overall"]["recommended_for_delivery"]:
                raise ExportValidationError(
                    "整本交付审查未通过。请先处理阻断风险并重新确认相关章节。"
                )
        data = self._load_full_export_input(
            project_id,
            allow_empty_sections=field_only_template,
        )
        export_id = uuid4()
        safe_project = re.sub(
            r'[\\/:*?"<>|\s]+', "_", data["project_name"]
        ).strip("_")[:80] or "项目"
        filename = (
            f"AI投标文件_{safe_project}_"
            f"{datetime.now().astimezone():%Y%m%d_%H%M%S}.docx"
        )
        storage_key = f"{project_id}/{filename}"
        destination = self.resolve_path(storage_key)
        temporary = destination.with_suffix(".tmp")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO export_records (
                        id, project_id, format, status, storage_key,
                        filename, export_scope
                    )
                    VALUES (
                        %s, %s, 'docx', 'running', %s, %s,
                        'full_proposal'
                    )
                    """,
                    (export_id, project_id, storage_key, filename),
                )
        try:
            if profile.generation_mode == "strict_template":
                template_path = profile_service.template_path(profile)
                if template_path is None or not template_path.is_file():
                    raise ExportValidationError("响应模板原文件不存在。")
                field_decisions = profile_service.template_field_decisions(
                    profile,
                    {"project_name": data["project_name"]},
                    EnterpriseFactResolver().resolve(project_id),
                    entity_context=(
                        EntityResolutionService().resolve_project(project_id)
                    ),
                )
                approved_values = {
                    item["field_key"]: item["value"]
                    for item in field_decisions
                    if item["status"] == "AUTO_FILL" and item["value"]
                }
                report = ResponseTemplateService().fill_docx(
                    template_content=template_path.read_bytes(),
                    output_path=temporary,
                    descriptor=profile.template_descriptor,
                    field_values=approved_values,
                    sections=data["sections"],
                    document_title=delivery_title(data["project_name"]),
                )
                profile_service.record_fill_report(
                    project_id,
                    {
                        **report.snapshot(),
                        "field_decisions": field_decisions,
                    },
                )
                self._validate_template_fill(report)
            else:
                build_full_proposal_docx(
                    temporary,
                    project_name=data["project_name"],
                    sections=data["sections"],
                    requirements=data["requirements"],
                )
            temporary.replace(destination)
        except ExportValidationError:
            temporary.unlink(missing_ok=True)
            self._mark_failed(export_id, "TEMPLATE_FILL_INCOMPLETE")
            raise
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            self._mark_failed(export_id, type(exc).__name__)
            raise ExportValidationError("整本 DOCX 导出失败。") from exc
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE export_records
                    SET status = 'succeeded', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (export_id,),
                )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'exported', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        pipeline = ControlledPipeline()
        run_id = pipeline.latest(project_id)
        pipeline.succeed(run_id, "export")
        return self.get(project_id, export_id)

    def create(
        self,
        project_id: UUID,
        section_id: UUID,
        section_version_id: UUID,
    ) -> dict:
        data = self._load_export_input(
            project_id,
            section_id,
            section_version_id,
        )
        export_id = uuid4()
        safe_title = re.sub(
            r'[\\/:*?"<>|\s]+',
            "_",
            data["section_title"],
        ).strip("_")[:80] or "技术方案"
        filename = (
            f"{safe_title}_{datetime.now().astimezone():%Y%m%d_%H%M%S}.docx"
        )
        storage_key = f"{project_id}/{filename}"
        destination = self.resolve_path(storage_key)
        temporary = destination.with_suffix(".tmp")
        destination.parent.mkdir(parents=True, exist_ok=True)

        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO export_records (
                        id, project_id, section_id, section_version_id,
                        format, status, storage_key, filename
                    )
                    VALUES (
                        %s, %s, %s, %s, 'docx', 'running', %s, %s
                    )
                    """,
                    (
                        export_id,
                        project_id,
                        section_id,
                        section_version_id,
                        storage_key,
                        filename,
                    ),
                )
        try:
            build_proposal_docx(
                temporary,
                project_name=data["project_name"],
                section_title=data["section_title"],
                content=data["content"],
                requirements=data["requirements"],
            )
            temporary.replace(destination)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            self._mark_failed(export_id, type(exc).__name__)
            raise ExportValidationError(
                "DOCX 导出失败，请稍后重试。"
            ) from exc

        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE export_records
                    SET status = 'succeeded', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (export_id,),
                )
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = 'exported', updated_at = NOW()
                    WHERE id = %s
                    """,
                    (project_id,),
                )
        return self.get(project_id, export_id)

    def get(self, project_id: UUID, export_id: UUID) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        id, project_id, section_id, section_version_id,
                        export_scope, format, status, filename,
                        error_code, error_message,
                        created_at, updated_at
                    FROM export_records
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, export_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ExportNotFoundError(str(export_id))
        return dict(row)

    def download_info(
        self,
        project_id: UUID,
        export_id: UUID,
    ) -> tuple[Path, str]:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT storage_key, filename, status
                    FROM export_records
                    WHERE project_id = %s AND id = %s
                    """,
                    (project_id, export_id),
                )
                row = cursor.fetchone()
        if row is None:
            raise ExportNotFoundError(str(export_id))
        if row["status"] != "succeeded":
            raise ExportValidationError("导出文件尚未生成完成。")
        path = self.resolve_path(row["storage_key"])
        if not path.is_file():
            raise ExportValidationError("导出文件不存在，请重新导出。")
        return path, row["filename"]

    @staticmethod
    def resolve_path(storage_key: str) -> Path:
        root = Path(settings.export_root).resolve()
        destination = (root / storage_key).resolve()
        if root not in destination.parents:
            raise ValueError("非法导出路径")
        return destination

    @staticmethod
    def _load_export_input(
        project_id: UUID,
        section_id: UUID,
        version_id: UUID,
    ) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                        projects.name AS project_name,
                        sections.title AS section_title,
                        sections.status AS section_status,
                        section_versions.content
                    FROM sections
                    JOIN projects ON projects.id = sections.project_id
                    JOIN section_versions
                        ON section_versions.section_id = sections.id
                    WHERE sections.project_id = %s
                      AND sections.id = %s
                      AND section_versions.id = %s
                    """,
                    (project_id, section_id, version_id),
                )
                section = cursor.fetchone()
                if section is None:
                    raise ExportValidationError(
                        "章节或章节版本不存在。"
                    )
                if section["section_status"] != "approved":
                    raise ExportValidationError(
                        "只有人工确认后的章节可以导出。"
                    )
                cursor.execute(
                    """
                    SELECT
                        requirements.normalized_text,
                        requirements.quote,
                        documents.filename,
                        source_chunks.locator_kind,
                        source_chunks.page_no,
                        source_chunks.paragraph_start,
                        source_chunks.paragraph_end
                    FROM section_requirements
                    JOIN requirements
                        ON requirements.id =
                           section_requirements.requirement_id
                    JOIN requirement_sources
                        ON requirement_sources.requirement_id =
                           requirements.id
                    JOIN source_chunks
                        ON source_chunks.id =
                           requirement_sources.source_chunk_id
                    JOIN documents
                        ON documents.id = source_chunks.document_id
                    WHERE section_requirements.section_id = %s
                    ORDER BY requirements.id, source_chunks.id
                    """,
                    (section_id,),
                )
                rows = cursor.fetchall()
        requirements: list[dict] = []
        by_text: dict[str, dict] = {}
        for row in rows:
            requirement = by_text.get(row["normalized_text"])
            if requirement is None:
                requirement = {
                    "normalized_text": row["normalized_text"],
                    "quote": row["quote"],
                    "sources": [],
                }
                by_text[row["normalized_text"]] = requirement
                requirements.append(requirement)
            requirement["sources"].append(
                {
                    "filename": row["filename"],
                    "locator": {
                        "kind": row["locator_kind"],
                        "page": row["page_no"],
                        "paragraph_start": row["paragraph_start"],
                        "paragraph_end": row["paragraph_end"],
                    },
                }
            )
        return {
            "project_name": section["project_name"],
            "section_title": section["section_title"],
            "content": SectionService.sanitize_generated_content(
                section["content"]
            ),
            "requirements": requirements,
        }

    @staticmethod
    def _validate_template_fill(report) -> None:
        # Unknown enterprise facts remain blank/placeholder for manual fill;
        # they must never be guessed, but they do not prevent a draft Word.
        # Missing section anchors would place generated content incorrectly
        # and therefore remain a real delivery blocker.
        if report.unresolved_sections:
            raise ExportValidationError(
                "响应模板无明确章节回填位置："
                + "、".join(report.unresolved_sections)
            )

    @staticmethod
    def _mark_failed(export_id: UUID, error_code: str) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE export_records
                    SET status = 'failed', error_code = %s,
                        error_message = 'DOCX 导出失败',
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (error_code, export_id),
                )

    @staticmethod
    def _load_full_export_input(
        project_id: UUID,
        *,
        allow_empty_sections: bool = False,
        allow_draft_sections: bool = False,
    ) -> dict:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT projects.name
                    FROM projects WHERE id = %s
                    """,
                    (project_id,),
                )
                project = cursor.fetchone()
                if project is None:
                    raise ExportValidationError("方案不存在。")
                cursor.execute(
                    """
                    SELECT sections.id, sections.title,
                           sections.status, section_versions.content
                    FROM sections
                    LEFT JOIN section_versions
                      ON section_versions.id = sections.current_version_id
                    WHERE sections.project_id = %s
                      AND EXISTS (
                          SELECT 1
                          FROM section_requirements
                          JOIN requirements
                            ON requirements.id =
                               section_requirements.requirement_id
                          WHERE section_requirements.section_id = sections.id
                            AND requirements.status <> 'rejected'
                            AND requirements.need_generation = TRUE
                      )
                    ORDER BY sections.sort_order, sections.created_at
                    """,
                    (project_id,),
                )
                sections = cursor.fetchall()
                if not sections and not allow_empty_sections:
                    raise ExportValidationError("技术方案尚无章节。")
                if not allow_draft_sections and any(
                    row["status"] != "approved" or not row["content"]
                    for row in sections
                ):
                    raise ExportValidationError(
                        "整本导出前必须逐章生成人工确认。"
                    )
                cursor.execute(
                    """
                    SELECT DISTINCT ON (requirements.id, source_chunks.id)
                        requirements.id,
                        requirements.normalized_text,
                        requirements.quote,
                        documents.filename,
                        source_chunks.locator_kind,
                        source_chunks.page_no,
                        source_chunks.paragraph_start,
                        source_chunks.paragraph_end
                    FROM requirements
                    JOIN requirement_sources
                      ON requirement_sources.requirement_id = requirements.id
                    JOIN source_chunks
                      ON source_chunks.id =
                         requirement_sources.source_chunk_id
                    JOIN documents
                      ON documents.id = source_chunks.document_id
                    WHERE requirements.project_id = %s
                      AND requirements.need_generation = TRUE
                      AND requirements.status <> 'rejected'
                    ORDER BY requirements.id, source_chunks.id
                    """,
                    (project_id,),
                )
                rows = cursor.fetchall()
        grouped: dict[UUID, dict] = {}
        for row in rows:
            item = grouped.setdefault(
                row["id"],
                {
                    "normalized_text": row["normalized_text"],
                    "quote": row["quote"],
                    "sources": [],
                },
            )
            item["sources"].append(
                {
                    "filename": row["filename"],
                    "locator": {
                        "kind": row["locator_kind"],
                        "page": row["page_no"],
                        "paragraph_start": row["paragraph_start"],
                        "paragraph_end": row["paragraph_end"],
                    },
                }
            )
        return {
            "project_name": project["name"],
            "sections": [
                {
                    **dict(row),
                    "content": SectionService.sanitize_generated_content(
                        row["content"]
                    ),
                }
                for row in sections
                if row["content"]
            ],
            "requirements": list(grouped.values()),
        }
