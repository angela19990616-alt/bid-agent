from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.database.db import connect
from app.knowledge.engine import EnterpriseKnowledgeEngine
from app.rules.engine import RuleEngine
from app.services.project_document_service import ProjectDocumentService
from app.services.processing_eta_service import ProcessingEtaService
from app.services.project_service import ProjectService
from app.services.proposal_plan_service import ProposalPlanService
from app.services.requirement_service import RequirementService
from app.services.section_service import SectionService
from app.workflows.controlled_pipeline import ControlledPipeline


class InvalidTenderDocumentError(Exception):
    def __init__(self, workspace_id: UUID, reason: str):
        super().__init__(reason)
        self.workspace_id = workspace_id
        self.reason = reason


class WorkspaceRetryError(Exception):
    pass


class WorkspaceService:
    def __init__(
        self,
        document_service: ProjectDocumentService | None = None,
        requirement_service: RequirementService | None = None,
        plan_service: ProposalPlanService | None = None,
        rule_engine: RuleEngine | None = None,
        knowledge_engine: EnterpriseKnowledgeEngine | None = None,
    ):
        self.document_service = document_service or ProjectDocumentService()
        self.requirement_service = requirement_service or RequirementService()
        self.plan_service = plan_service or ProposalPlanService()
        self.rule_engine = rule_engine or RuleEngine()
        self.knowledge_engine = (
            knowledge_engine or EnterpriseKnowledgeEngine()
        )

    def create_from_upload(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> dict:
        workspace, document_id, run_id = self.prepare_from_upload(
            filename,
            content_type,
            content,
        )
        self.complete_prepared_upload(workspace["id"], document_id, run_id)
        return self.get(workspace["id"])

    def prepare_from_upload(
        self,
        filename: str,
        content_type: str | None,
        content: bytes,
    ) -> tuple[dict, UUID, UUID]:
        name = Path(filename).stem[:200].strip() or "未命名招标文件"
        workspace = ProjectService().create(name)
        pipeline = ControlledPipeline()
        run_id = pipeline.start(workspace.id)
        try:
            self._set_status(workspace.id, "validating")
            pipeline.record(
                run_id,
                "document_validator",
                details={
                    "filename": filename,
                    "size_bytes": len(content),
                    "extension": Path(filename).suffix.lower(),
                },
            )
            extraction_rules = self.rule_engine.load("extraction")
            pipeline.record(
                run_id,
                "load_extraction_rules",
                rule_snapshot=extraction_rules.snapshot(),
            )
            pipeline.record(run_id, "parser")
            document = self.document_service.upload_and_parse(
                workspace.id,
                filename,
                content_type,
                content,
                extraction_rules,
            )
            if document.validation_status != "valid":
                self._set_status(workspace.id, "draft")
                raise InvalidTenderDocumentError(
                    workspace.id,
                    document.validation_reason
                    or "文件不是有效招标文件。",
                )
            self._set_status(workspace.id, "extracting")
            return self.get(workspace.id), document.id, run_id
        except Exception as exc:
            pipeline.fail(run_id, type(exc).__name__, str(exc))
            raise

    def complete_prepared_upload(
        self,
        workspace_id: UUID,
        document_id: UUID,
        run_id: UUID,
    ) -> None:
        pipeline = ControlledPipeline()
        try:
            extraction_rules = self.rule_engine.load("extraction")
            pipeline.record(run_id, "requirement_extractor")
            self.requirement_service.extract(
                workspace_id,
                [document_id],
                extraction_rules,
            )
            pipeline.record(run_id, "requirement_reviewer")

            technical = self.requirement_service.list(
                workspace_id, need_generation=True
            )
            pipeline.record(run_id, "load_enterprise_knowledge")
            knowledge_matches = self.knowledge_engine.match(
                section_title=ProjectService().get(workspace_id).name,
                requirements=technical,
                exclude_document_ids={document_id},
                exclude_project_id=workspace_id,
            )
            pipeline.record(
                run_id,
                "knowledge_matching",
                knowledge_snapshot=[
                    item.snapshot() for item in knowledge_matches
                ],
                details={"match_count": len(knowledge_matches)},
            )
            writing_rules = self.rule_engine.load("writing")
            pipeline.record(
                run_id,
                "load_writing_rules",
                rule_snapshot=writing_rules.snapshot(),
            )
            self._set_status(workspace_id, "planning")
            pipeline.record(run_id, "proposal_planner")
            self.plan_service.create_recommended_outline(
                workspace_id, writing_rules
            )
        except Exception as exc:
            self._set_status(workspace_id, "draft")
            pipeline.fail(run_id, type(exc).__name__, str(exc))
            raise

    def prepare_retry(self, workspace_id: UUID) -> tuple[dict, UUID, UUID]:
        workspace = ProjectService().get(workspace_id)
        if workspace.status not in {"draft", "extracting", "planning"}:
            raise WorkspaceRetryError(
                "当前方案不处于可重试的处理状态。"
            )
        documents = self.document_service.list(workspace_id)
        document = next(
            (
                item
                for item in documents
                if item.validation_status == "valid"
            ),
            None,
        )
        if document is None:
            raise WorkspaceRetryError("没有可用于继续处理的有效招标文件。")
        pipeline = ControlledPipeline()
        run_id = pipeline.start(workspace_id)
        pipeline.record(
            run_id,
            "document_validator",
            details={"resume": True},
        )
        pipeline.record(run_id, "parser", details={"resume": True})
        self._set_status(workspace_id, "extracting")
        return self.get(workspace_id), document.id, run_id

    def get(self, workspace_id: UUID) -> dict:
        workspace = ProjectService().get(workspace_id)
        documents = self.document_service.list(workspace_id)
        technical = self.requirement_service.list(
            workspace_id,
            need_generation=True,
        )
        compliance = self.requirement_service.list(
            workspace_id,
            need_generation=False,
        )
        source_count = documents[0].source_count if documents else 0
        estimate = ProcessingEtaService.estimate(
            workspace_id,
            status=workspace.status,
            created_at=workspace.created_at,
            source_count=source_count,
        )
        return {
            "id": workspace.id,
            "name": workspace.name,
            "status": workspace.status,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "document": documents[0] if documents else None,
            "technical_requirements": technical,
            "compliance_reminder_count": len(compliance),
            "outline": SectionService().list(workspace_id),
            "estimated_remaining_seconds_low": (
                estimate.remaining_seconds_low
            ),
            "estimated_remaining_seconds_high": (
                estimate.remaining_seconds_high
            ),
            "estimate_sample_count": estimate.sample_count,
            "estimate_basis": estimate.basis,
        }

    @staticmethod
    def _set_status(workspace_id: UUID, status: str) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE projects
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, workspace_id),
                )
