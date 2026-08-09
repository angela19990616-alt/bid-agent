from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.database.db import connect
from app.rules.engine import RuleEngine
from app.services.project_document_service import ProjectDocumentService
from app.services.processing_eta_service import ProcessingEtaService
from app.services.model_budget_service import ModelBudgetService
from app.services.project_service import ProjectService
from app.services.proposal_plan_service import ProposalPlanService
from app.services.requirement_service import RequirementService
from app.services.section_service import SectionService
from app.services.workspace_job_service import WorkspaceJobService
from app.knowledge.default_case_library import default_case_library_summary
from app.knowledge.enterprise_fact_resolver import EnterpriseFactResolver
from app.knowledge.case_fact_resolver import CaseFactResolver
from app.services.generation_profile_service import GenerationProfileService
from app.services.response_template_service import ResponseTemplateService
from app.services.entity_resolution_service import EntityResolutionService
from app.core.semantic_variables import SlotDeduplicationEngine
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
        generation_profile_service: GenerationProfileService | None = None,
        enterprise_fact_resolver: EnterpriseFactResolver | None = None,
        case_fact_resolver: CaseFactResolver | None = None,
        entity_resolution_service: EntityResolutionService | None = None,
    ):
        self.document_service = document_service or ProjectDocumentService()
        self.requirement_service = requirement_service or RequirementService()
        self.plan_service = plan_service or ProposalPlanService()
        self.rule_engine = rule_engine or RuleEngine()
        self.generation_profile_service = (
            generation_profile_service or GenerationProfileService()
        )
        self.enterprise_fact_resolver = (
            enterprise_fact_resolver or EnterpriseFactResolver()
        )
        self.case_fact_resolver = case_fact_resolver or CaseFactResolver()
        self.entity_resolution_service = (
            entity_resolution_service or EntityResolutionService()
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
            pipeline.record(
                run_id,
                "document_ingestion",
                details={
                    "document_id": str(document.id),
                    "source_count": document.source_count,
                },
            )
            template_rules = self.rule_engine.load("template_generation")
            pipeline.record(
                run_id,
                "load_template_generation_rules",
                rule_snapshot=template_rules.snapshot(),
            )
            profile = self.generation_profile_service.get(workspace.id)
            pipeline.record(
                run_id,
                "response_template_detection",
                details={
                    "detected": bool(
                        profile.template_descriptor.get("detected", False)
                    ),
                    "source_format": profile.template_descriptor.get(
                        "source_format"
                    ),
                },
            )
            pipeline.record(
                run_id,
                "generation_mode_decision",
                details={"generation_mode": profile.generation_mode},
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
            budget = ModelBudgetService.configure_for_document(
                run_id,
                document_id,
            )
            pipeline.record(run_id, "requirement_extractor")
            pipeline.record(
                run_id,
                "model_budget",
                details=budget,
            )
            classification_rules = self.rule_engine.load("classification")
            response_strategy_rules = self.rule_engine.load(
                "response_strategy"
            )
            self.requirement_service.extract(
                workspace_id,
                [document_id],
                extraction_rules,
                classification_rules,
                run_id,
                response_strategy_rules,
            )

            profile = self.generation_profile_service.get(workspace_id)
            if profile.writer_strategy is None:
                # A PDF conversion failure is not evidence that the tender has
                # no template. Keep the parsed requirements, but never invent
                # a second outline while the source structure is unresolved.
                self._set_status(workspace_id, "outline_ready")
                pipeline.succeed(run_id, "generation_mode_decision")
                return

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
            pipeline.succeed(run_id, "proposal_planner")
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
        requirements = self.requirement_service.list(workspace_id)
        technical = [
            item for item in requirements
            if item["response_action"] == "write_into_proposal"
            and item.get("proposal_relevance", True)
            and (
                item.get("target_chapter", item.get("proposal_mapping"))
                is not None
                or item.get("need_generation", False)
            )
        ]
        compliance = [
            item for item in requirements if not item["need_generation"]
        ]
        response_summary = {
            "total": len(requirements),
            "proposal": sum(
                item["response_action"] == "write_into_proposal"
                for item in requirements
            ),
            "scoring": sum(
                item["scoring_impact"] == "score_item"
                for item in requirements
            ),
            "compliance": sum(
                item["type"] in {
                    "commercial_requirement",
                    "qualification_requirement",
                    "compliance_requirement",
                    "format_requirement",
                    "document_structure_requirement",
                }
                for item in requirements
            ),
            "risk": sum(
                (
                    item["priority"] == "P0"
                    if "priority" in item
                    else item["scoring_impact"] == "penalty_risk"
                )
                for item in requirements
            ),
        }
        source_count = documents[0].source_count if documents else 0
        estimate = ProcessingEtaService.estimate(
            workspace_id,
            status=workspace.status,
            created_at=workspace.created_at,
            source_count=source_count,
        )
        budget = ModelBudgetService.summary_for_project(workspace_id)
        profile = self.generation_profile_service.get(workspace_id)
        case_library = default_case_library_summary()
        enterprise_facts = self.enterprise_fact_resolver.resolve(workspace_id)
        entity_context = self.entity_resolution_service.resolve_project(
            workspace_id
        )
        variable_decisions = (
            self.generation_profile_service.template_variable_decisions(
                profile,
                {"project_name": workspace.name},
                enterprise_facts,
                self.case_fact_resolver.resolve(workspace_id),
                entity_context,
            )
        )
        job = WorkspaceJobService.latest_status(workspace_id)
        return {
            "id": workspace.id,
            "name": workspace.name,
            "status": workspace.status,
            "created_at": workspace.created_at,
            "updated_at": workspace.updated_at,
            "document": documents[0] if documents else None,
            "technical_requirements": technical,
            "compliance_reminder_count": len(compliance),
            "response_summary": response_summary,
            "outline": SectionService().list(workspace_id),
            "estimated_remaining_seconds_low": (
                estimate.remaining_seconds_low
            ),
            "estimated_remaining_seconds_high": (
                estimate.remaining_seconds_high
            ),
            "estimate_sample_count": estimate.sample_count,
            "estimate_basis": estimate.basis,
            "processing_error_code": (
                job["error_code"]
                if job and job["status"] == "failed"
                else None
            ),
            "processing_error_message": (
                job["error_message"]
                if job and job["status"] == "failed"
                else None
            ),
            "processing_retryable": bool(
                job and job["status"] == "failed" and documents
            ),
            "processing_job_status": job["status"] if job else None,
            "processing_job_progress": job["progress"] if job else 0,
            "processing_job_type": job["job_type"] if job else None,
            "generation_mode": profile.generation_mode,
            "writer_strategy": profile.writer_strategy,
            "template_conversion_status": profile.template_conversion_status,
            "template_conversion_report": (
                profile.template_conversion_report or {}
            ),
            "historical_case_mode": profile.historical_case_mode,
            "template_filename": profile.template_filename,
            "template_fidelity": profile.template_descriptor.get(
                "fidelity"
            ),
            "template_fonts": (
                profile.template_descriptor.get("font_profile", {}).get(
                    "detected_fonts", []
                )
            ),
            "template_font_policy": (
                profile.template_descriptor.get("font_profile", {}).get(
                    "policy", "inherit_source_template"
                )
            ),
            "template_required_fields": ResponseTemplateService.required_fields(
                profile.template_descriptor
            ),
            "template_field_values": profile.template_field_values,
            "template_field_decisions": (
                SlotDeduplicationEngine.fan_out(variable_decisions)
            ),
            "template_variable_decisions": [
                SlotDeduplicationEngine.public_snapshot(item)
                for item in variable_decisions
            ],
            "template_actions": profile.template_descriptor.get(
                "actions", []
            ),
            "case_library_count": case_library["count"],
            "case_library_name": case_library["name"],
            "case_library_scope": case_library["scope"],
            "case_library_fact_usage": case_library["fact_usage"],
            "template_outline": profile.template_descriptor.get(
                "outline", []
            ),
            **budget,
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
