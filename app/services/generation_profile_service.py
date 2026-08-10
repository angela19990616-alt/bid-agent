from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row

from app.config.settings import settings
from app.database.db import connect
from app.services.response_template_service import ResponseTemplateService
from app.core.strict_fill import (
    DataSensitivity,
    EnterpriseFact,
    StrictFillDecisionEngine,
    TemplateField,
)
from app.knowledge.case_fact_resolver import CaseFactCandidate
from app.knowledge.case_fact_resolver import CaseFactResolver
from app.knowledge.enterprise_fact_resolver import EnterpriseFactResolver
from app.core.entity_resolution import (
    DocumentSlot,
    EntityResolutionContext,
    EntityResolutionEngine,
    EntityType,
    FillStrategy,
    ROLE_LABELS,
    SlotContextClassifier,
)
from app.services.entity_resolution_service import EntityResolutionService
from app.core.semantic_variables import SlotDeduplicationEngine
from app.services.pdf_template_conversion_service import (
    PdfTemplateConversionService,
)
from app.services.slot_semantic_resolution_service import (
    SlotSemanticResolutionService,
)


TEMPLATE_FIELD_LABELS = {
    "project_name": "项目名称",
    "project_number": "项目编号",
    "project_reference": "项目名称及编号",
    "bidder_name": "供应商名称",
    "legal_representative": "法定代表人",
    "authorized_representative": "授权代表",
    "project_manager_name": "项目负责人",
    "technical_lead_name": "技术负责人",
    "signatory_name": "签字人",
    "person_id_number": "身份证号码",
    "person_title": "职务",
    "date": "日期",
    "bid_response_signing_date": "投标文件签署日期",
    "registered_address": "注册地址",
    "postal_code": "邮政编码",
    "contact_person": "联系人",
    "contact_phone": "联系电话",
    "fax": "传真",
    "website": "网址",
    "enterprise_qualification": "企业资质等级",
    "bank_account": "银行账号",
    "bid_round": "报价轮次",
}


@dataclass(frozen=True)
class GenerationProfile:
    project_id: UUID
    generation_mode: str
    historical_case_mode: str
    template_descriptor: dict[str, Any]
    template_field_values: dict[str, str]
    template_storage_key: str | None = None
    template_filename: str | None = None
    last_fill_report: dict[str, Any] | None = None
    writer_strategy: str | None = "planned_proposal_writer"
    converted_template_storage_key: str | None = None
    template_conversion_status: str = "not_required"
    template_conversion_report: dict[str, Any] | None = None


class GenerationProfileService:
    def __init__(
        self,
        template_service: ResponseTemplateService | None = None,
        conversion_service: PdfTemplateConversionService | None = None,
        semantic_resolution_service: (
            SlotSemanticResolutionService | None
        ) = None,
    ):
        self.template_service = template_service or ResponseTemplateService()
        self.conversion_service = (
            conversion_service or PdfTemplateConversionService()
        )
        self.semantic_resolution_service = (
            semantic_resolution_service or SlotSemanticResolutionService()
        )

    def inspect_document(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
    ) -> GenerationProfile:
        source_descriptor = self.template_service.detect(filename, content)
        descriptor = source_descriptor
        converted_content: bytes | None = None
        conversion_status = "not_required"
        conversion_report: dict[str, Any] = {}
        mode = self.mode_for_descriptor(source_descriptor.snapshot())
        if Path(filename).suffix.lower() == ".pdf":
            conversion = self.conversion_service.convert(content)
            conversion_status = conversion.status
            conversion_report = conversion.snapshot()
            converted_content = conversion.content
            if converted_content is not None:
                converted_descriptor = self.template_service.detect(
                    f"{Path(filename).stem}-converted.docx",
                    converted_content,
                )
                if converted_descriptor.detected:
                    descriptor = converted_descriptor
                    mode = "strict_template"
                    conversion_report["template_detected"] = True
                    conversion_report["structure_validation"] = "passed"
                else:
                    descriptor = converted_descriptor
                    mode = "planned"
                    conversion_report["template_detected"] = False
                    conversion_report["structure_validation"] = "passed"
            else:
                mode = "template_conversion_required"
                conversion_report["template_detected"] = bool(
                    source_descriptor.detected
                )
                conversion_report["structure_validation"] = "failed"
        source_fields, source_evidence = (
            self.template_service.extract_source_fields_with_evidence(
                filename, content
            )
        )
        descriptor_snapshot = descriptor.snapshot()
        descriptor_snapshot["ontology_version"] = (
            SlotContextClassifier.ontology_version()
        )
        descriptor_snapshot["source_format_original"] = Path(
            filename
        ).suffix.lower().lstrip(".")
        descriptor_snapshot["conversion"] = conversion_report
        if mode == "strict_template" and converted_content is not None:
            descriptor_snapshot["fidelity"] = "converted_template_validated"
        descriptor_snapshot["source_evidence"] = source_evidence
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id, storage_key FROM documents
                    WHERE project_id = %s AND public_id = %s
                    """,
                    (project_id, document_id),
                )
                document = cursor.fetchone()
                if document is None:
                    raise ValueError("模板来源文件不存在。")
                converted_storage_key = None
                if converted_content is not None:
                    converted_storage_key = str(
                        Path(document["storage_key"]).with_name(
                            f"{Path(document['storage_key']).stem}-converted.docx"
                        )
                    )
                    converted_path = self._safe_storage_path(
                        converted_storage_key
                    )
                    converted_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = converted_path.with_suffix(".docx.tmp")
                    temporary.write_bytes(converted_content)
                    temporary.replace(converted_path)
                cursor.execute(
                    """
                    INSERT INTO proposal_generation_profiles (
                        project_id, generation_mode, template_document_id,
                        template_descriptor, template_field_values,
                        writer_strategy, converted_template_storage_key,
                        template_conversion_status,
                        template_conversion_report
                    )
                    VALUES (
                        %s, %s, %s, %s::jsonb, %s::jsonb,
                        %s, %s, %s, %s::jsonb
                    )
                    ON CONFLICT (project_id) DO UPDATE SET
                        generation_mode = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.generation_mode
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.generation_mode
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.generation_mode
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.generation_mode
                            ELSE EXCLUDED.generation_mode
                        END,
                        template_document_id = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_document_id
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_document_id
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.template_document_id
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.template_document_id
                            ELSE EXCLUDED.template_document_id
                        END,
                        template_descriptor = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_descriptor
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_descriptor
                            WHEN EXCLUDED.generation_mode =
                                'pdf_template_manual_fill'
                                THEN EXCLUDED.template_descriptor
                            WHEN proposal_generation_profiles.generation_mode =
                                'pdf_template_manual_fill'
                                THEN proposal_generation_profiles.template_descriptor
                            ELSE EXCLUDED.template_descriptor
                        END,
                        template_field_values = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.template_field_values ||
                                     proposal_generation_profiles.template_field_values
                            ELSE proposal_generation_profiles.template_field_values
                        END,
                        writer_strategy = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN 'strict_template_writer'
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN 'strict_template_writer'
                            WHEN EXCLUDED.generation_mode = 'planned'
                                THEN 'planned_proposal_writer'
                            ELSE NULL
                        END,
                        converted_template_storage_key = CASE
                            WHEN EXCLUDED.generation_mode = 'strict_template'
                                THEN EXCLUDED.converted_template_storage_key
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.converted_template_storage_key
                            ELSE EXCLUDED.converted_template_storage_key
                        END,
                        template_conversion_status = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                AND EXCLUDED.generation_mode <> 'strict_template'
                                THEN proposal_generation_profiles.template_conversion_status
                            ELSE EXCLUDED.template_conversion_status
                        END,
                        template_conversion_report = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                AND EXCLUDED.generation_mode <> 'strict_template'
                                THEN proposal_generation_profiles.template_conversion_report
                            ELSE EXCLUDED.template_conversion_report
                        END,
                        updated_at = NOW()
                    """,
                    (
                        project_id,
                        mode,
                        document["id"] if descriptor.detected else None,
                        json.dumps(descriptor_snapshot, ensure_ascii=False),
                        json.dumps(source_fields, ensure_ascii=False),
                        self.writer_strategy_for_mode(mode),
                        converted_storage_key,
                        conversion_status,
                        json.dumps(conversion_report, ensure_ascii=False),
                    ),
                )
        return self.get(project_id)

    def refine_template_semantics(
        self,
        project_id: UUID,
        *,
        workflow_run_id: UUID | None = None,
    ) -> dict[str, Any]:
        """AI-review template slot meaning without ever generating values."""
        profile = self.get(project_id)
        descriptor = dict(profile.template_descriptor)
        fields = list(descriptor.get("fields") or ())
        existing_report = descriptor.get("ai_semantic_resolution") or {}
        if (
            existing_report.get("status") in {
                "completed", "review_required",
            }
            and existing_report.get("rule_version")
            == self.semantic_resolution_service.rule_version()
        ):
            return dict(existing_report)
        if profile.generation_mode != "strict_template" or not fields:
            report = {
                "status": "skipped",
                "reviewed_slot_count": 0,
                "reason": "当前文件没有需要 AI 识别的严格回填空位。",
            }
            descriptor["ai_semantic_resolution"] = report
        else:
            result = self.semantic_resolution_service.resolve(
                fields,
                list(descriptor.get("actions") or ()),
                workflow_run_id=workflow_run_id,
            )
            descriptor["fields"] = list(result.fields)
            descriptor["actions"] = list(result.actions)
            descriptor["semantic_audit"] = result.report.get(
                "semantic_audit", {}
            )
            descriptor["ai_semantic_resolution"] = result.report
            report = result.report
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET template_descriptor = %s::jsonb,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (
                        json.dumps(descriptor, ensure_ascii=False),
                        project_id,
                    ),
                )
        return report

    @staticmethod
    def record_pdf_conversion_failure(
        *,
        project_id: UUID,
        document_id: UUID,
        message: str,
    ) -> None:
        """Persist a safe stop state instead of misclassifying PDF as no-template."""
        report = {
            "status": "failed",
            "message": message[:500],
            "template_detected": None,
            "structure_validation": "failed",
        }
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT id FROM documents
                    WHERE project_id = %s AND public_id = %s
                    """,
                    (project_id, document_id),
                )
                document = cursor.fetchone()
                if document is None:
                    raise ValueError("模板来源文件不存在。")
                cursor.execute(
                    """
                    INSERT INTO proposal_generation_profiles (
                        project_id, generation_mode, template_document_id,
                        template_descriptor, template_field_values,
                        writer_strategy, template_conversion_status,
                        template_conversion_report
                    ) VALUES (
                        %s, 'template_conversion_required', %s,
                        %s::jsonb, '{}'::jsonb, NULL, 'failed', %s::jsonb
                    )
                    ON CONFLICT (project_id) DO UPDATE SET
                        generation_mode = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template' THEN 'strict_template'
                            ELSE 'template_conversion_required'
                        END,
                        writer_strategy = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template' THEN 'strict_template_writer'
                            ELSE NULL
                        END,
                        template_conversion_status = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_conversion_status
                            ELSE 'failed'
                        END,
                        template_conversion_report = CASE
                            WHEN proposal_generation_profiles.generation_mode =
                                'strict_template'
                                THEN proposal_generation_profiles.template_conversion_report
                            ELSE EXCLUDED.template_conversion_report
                        END,
                        updated_at = NOW()
                    """,
                    (
                        project_id,
                        document["id"],
                        json.dumps({
                            "detected": False,
                            "source_format": "pdf",
                            "conversion": report,
                        }, ensure_ascii=False),
                        json.dumps(report, ensure_ascii=False),
                    ),
                )

    @staticmethod
    def mode_for_descriptor(descriptor: dict[str, Any]) -> str:
        if descriptor.get("detected") and descriptor.get("source_format") == "docx":
            return "strict_template"
        if descriptor.get("detected") and descriptor.get("source_format") == "pdf":
            return "pdf_template_manual_fill"
        return "planned"

    @staticmethod
    def writer_strategy_for_mode(mode: str) -> str | None:
        if mode == "strict_template":
            return "strict_template_writer"
        if mode == "planned":
            return "planned_proposal_writer"
        return None

    @staticmethod
    def preferred_mode(existing: str, incoming: str) -> str:
        priority = {
            "planned": 1,
            "template_conversion_required": 2,
            "pdf_template_manual_fill": 2,
            "strict_template": 3,
        }
        return (
            incoming
            if priority.get(incoming, 0) >= priority.get(existing, 0)
            else existing
        )

    @staticmethod
    def get(project_id: UUID) -> GenerationProfile:
        with connect() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT p.project_id, p.generation_mode,
                           p.historical_case_mode, p.template_descriptor,
                           p.template_field_values,
                           p.last_fill_report,
                           p.writer_strategy,
                           p.converted_template_storage_key,
                           p.template_conversion_status,
                           p.template_conversion_report,
                           d.storage_key AS template_storage_key,
                           d.filename AS template_filename
                    FROM proposal_generation_profiles p
                    LEFT JOIN documents d ON d.id = p.template_document_id
                    WHERE p.project_id = %s
                    """,
                    (project_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return GenerationProfile(
                project_id=project_id,
                generation_mode="planned",
                historical_case_mode="closest_case",
                template_descriptor={},
                template_field_values={},
                last_fill_report={},
                writer_strategy="planned_proposal_writer",
                template_conversion_report={},
            )
        profile = GenerationProfile(**row)
        if (
            profile.generation_mode == "strict_template"
            and profile.template_descriptor.get("ontology_version")
            != SlotContextClassifier.ontology_version()
        ):
            profile = GenerationProfileService._refresh_template_ontology(
                profile
            )
        return profile

    @staticmethod
    def _refresh_template_ontology(
        profile: GenerationProfile,
    ) -> GenerationProfile:
        """Re-analyse existing templates once when ontology rules change."""
        path = GenerationProfileService.template_path(profile)
        if path is None or not path.is_file():
            return profile
        filename = profile.template_filename or path.name
        if profile.converted_template_storage_key:
            filename = f"{Path(filename).stem}-converted.docx"
        descriptor = ResponseTemplateService().detect(
            filename, path.read_bytes()
        ).snapshot()
        descriptor["ontology_version"] = (
            SlotContextClassifier.ontology_version()
        )
        previous = profile.template_descriptor
        for key in (
            "source_evidence", "source_format_original", "conversion",
        ):
            if key in previous:
                descriptor[key] = previous[key]
        if previous.get("fidelity") == "converted_template_validated":
            descriptor["fidelity"] = "converted_template_validated"
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET template_descriptor = %s::jsonb,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (
                        json.dumps(descriptor, ensure_ascii=False),
                        profile.project_id,
                    ),
                )
        return GenerationProfile(
            **{
                **profile.__dict__,
                "template_descriptor": descriptor,
            }
        )

    @staticmethod
    def _raw_template_field_decisions(
        profile: GenerationProfile,
        fallback_values: dict[str, str] | None = None,
        enterprise_facts: list[EnterpriseFact] | None = None,
        case_candidates: dict[str, CaseFactCandidate] | None = None,
        entity_context: EntityResolutionContext | None = None,
    ) -> list[dict[str, Any]]:
        required = ResponseTemplateService.required_fields(
            profile.template_descriptor
        )
        fallback_values = fallback_values or {}
        keys = list(dict.fromkeys([
            *required,
            *profile.template_field_values,
            *fallback_values,
        ]))
        reviews = (getattr(profile, "last_fill_report", None) or {}).get(
            "field_reviews", {}
        )
        field_metadata = {
            item.get("field_key"): item
            for item in profile.template_descriptor.get("fields", [])
            if item.get("field_key")
        }
        engine = StrictFillDecisionEngine()
        decisions: list[dict[str, Any]] = []
        for key in keys:
            metadata = field_metadata.get(key, {})
            canonical_key = str(metadata.get("canonical_key") or key)
            value = (
                profile.template_field_values.get(key)
                or profile.template_field_values.get(canonical_key)
                or fallback_values.get(key)
                or fallback_values.get(canonical_key)
                or ""
            ).strip()
            if canonical_key == "project_reference" and not value:
                project_name = (
                    profile.template_field_values.get("project_name")
                    or fallback_values.get("project_name")
                    or ""
                ).strip()
                project_number = (
                    profile.template_field_values.get("project_number")
                    or fallback_values.get("project_number")
                    or ""
                ).strip()
                if project_name and project_number:
                    value = f"{project_name}（项目编号：{project_number}）"
            if canonical_key == "bid_response_signing_date" and not value:
                value = (
                    profile.template_field_values.get("date")
                    or fallback_values.get("date")
                    or ""
                ).strip()
            slot = GenerationProfileService._slot_for_field(key, metadata)
            entity_resolution = (
                EntityResolutionEngine().resolve(slot, entity_context)
                if entity_context is not None
                else None
            )
            facts: list[EnterpriseFact] = [
                fact
                for fact in (enterprise_facts or [])
                if fact.canonical_key == canonical_key
            ]
            if value:
                review = reviews.get(key, {})
                source_evidence = (
                    profile.template_descriptor.get("source_evidence", {})
                    .get(key, {})
                )
                confirmed = (
                    review.get("status") == "confirmed"
                    and review.get("value") == value
                )
                procurement_fact = canonical_key in {
                    "project_name", "project_number", "project_reference",
                }
                expected_source = metadata.get("expected_source")
                resolved_entity_id = (
                    str(entity_resolution.person.id)
                    if (
                        confirmed
                        and entity_resolution is not None
                        and entity_resolution.person is not None
                    )
                    else str(entity_resolution.organization.id)
                    if (
                        confirmed
                        and entity_resolution is not None
                        and entity_resolution.organization is not None
                    )
                    else None
                )
                facts.append(EnterpriseFact(
                    canonical_key=canonical_key,
                    value=value,
                    source_type=(
                        "tender_document"
                        if procurement_fact
                        else "manual_verified" if confirmed
                        else expected_source or "manual_input"
                    ),
                    source_reference=(
                        profile.template_filename or "uploaded_tender"
                        if procurement_fact
                        else review.get("source_reference")
                        or "本项目已审核资料"
                    ),
                    confidence=1.0 if procurement_fact or confirmed else 0.8,
                    verified=procurement_fact or confirmed,
                    entity_id=resolved_entity_id,
                    semantic_field=slot.semantic_field,
                    sensitivity=(
                        DataSensitivity.SENSITIVE
                        if (
                            expected_source == "controlled_personnel_vault"
                            and not confirmed
                        )
                        else DataSensitivity.NORMAL
                    ),
                    evidence_title=(
                        review.get("evidence_title")
                        or source_evidence.get("title")
                        or profile.template_filename
                    ),
                    evidence_excerpt=(
                        review.get("evidence_excerpt")
                        or source_evidence.get("excerpt")
                    ),
                    evidence_location=(
                        review.get("evidence_location")
                        or source_evidence.get("location")
                    ),
                ))
            if entity_resolution is not None and not (
                value
                and reviews.get(key, {}).get("status") == "confirmed"
                and reviews.get(key, {}).get("value") == value
            ):
                facts.extend(
                    GenerationProfileService._entity_facts(
                        canonical_key, slot, entity_resolution
                    )
                )
            field = TemplateField(
                field_id=key,
                label=metadata.get("label") or TEMPLATE_FIELD_LABELS.get(key, key),
                canonical_key=canonical_key,
                required=key in required,
                source_location=metadata.get("source_location") or "原响应模板",
                semantic_field=slot.semantic_field,
                expected_entity_type=(
                    slot.expected_entity_type.value
                    if slot.expected_entity_type else None
                ),
                expected_role=(
                    slot.expected_role.value if slot.expected_role else None
                ),
                slot_id=slot.slot_id,
                surrounding_text=slot.surrounding_text,
            )
            decision = engine.decide(
                field, facts, entity_resolution=entity_resolution
            )
            candidate = (case_candidates or {}).get(canonical_key)
            if (
                decision.status.value == "MISSING"
                and candidate is not None
                and slot.expected_entity_type not in {
                    EntityType.PERSON, EntityType.ORGANIZATION,
                    EntityType.BUSINESS_CASE, EntityType.CERTIFICATE,
                    EntityType.RESPONSE_ITEM,
                }
            ):
                alternative_count = len(candidate.alternatives)
                decisions.append({
                    "field_key": key,
                    "canonical_key": canonical_key,
                    "label": field.label,
                    "expected_value_type": engine.field_type(canonical_key),
                    "expected_value_type_label": engine.field_type_label(canonical_key),
                    "type_validation": "passed",
                    "value": candidate.value,
                    "source_type": "historical_case",
                    "source_reference": candidate.source_title,
                    "confidence": candidate.confidence,
                    "status": "REVIEW_REQUIRED",
                    "reason": (
                        "从五份机构私有案例中匹配到候选值，"
                        + (
                            f"另有 {alternative_count} 个不同候选，系统不自动判断口径；"
                            if alternative_count else ""
                        )
                        + "确认后才可用于正式交付。"
                    ),
                    "required": field.required,
                    "evidence_title": candidate.source_title,
                    "evidence_excerpt": candidate.source_excerpt,
                    "evidence_location": candidate.source_location,
                    "evidence_match_count": candidate.match_count,
                    "evidence_alternatives": list(candidate.alternatives),
                    "semantic_resolution": metadata.get(
                        "semantic_resolution"
                    ) or {},
                    **GenerationProfileService._resolution_snapshot(
                        slot, entity_resolution, entity_context
                    ),
                })
                continue
            decisions.append({
                "field_key": key,
                "canonical_key": canonical_key,
                "label": field.label,
                "expected_value_type": engine.field_type(canonical_key),
                "expected_value_type_label": engine.field_type_label(canonical_key),
                "type_validation": (
                    "passed" if decision.value else "missing"
                ),
                "value": decision.value,
                "source_type": decision.source_type,
                "source_reference": decision.source_reference,
                "confidence": decision.confidence,
                "status": decision.status.value,
                "reason": decision.reason,
                "required": field.required,
                "evidence_title": (
                    reviews.get(key, {}).get("evidence_title")
                    or (
                        profile.template_descriptor.get("source_evidence", {})
                        .get(key, {}).get("title")
                    )
                    or decision.evidence_title
                    or decision.source_reference
                ),
                "evidence_excerpt": (
                    reviews.get(key, {}).get("evidence_excerpt")
                    or profile.template_descriptor.get("source_evidence", {})
                    .get(key, {}).get("excerpt")
                    or decision.evidence_excerpt
                ),
                "evidence_location": (
                    reviews.get(key, {}).get("evidence_location")
                    or profile.template_descriptor.get("source_evidence", {})
                    .get(key, {}).get("location")
                    or decision.evidence_location
                    or decision.source_type
                ),
                "evidence_match_count": reviews.get(key, {}).get(
                    "evidence_match_count", 1 if decision.value else 0
                ),
                "evidence_alternatives": reviews.get(key, {}).get(
                    "evidence_alternatives", []
                ),
                "semantic_resolution": metadata.get(
                    "semantic_resolution"
                ) or {},
                **GenerationProfileService._resolution_snapshot(
                    slot, entity_resolution, entity_context
                ),
            })
        return decisions

    @staticmethod
    def template_variable_decisions(
        profile: GenerationProfile,
        fallback_values: dict[str, str] | None = None,
        enterprise_facts: list[EnterpriseFact] | None = None,
        case_candidates: dict[str, CaseFactCandidate] | None = None,
        entity_context: EntityResolutionContext | None = None,
    ) -> list[dict[str, Any]]:
        raw = GenerationProfileService._raw_template_field_decisions(
            profile,
            fallback_values,
            enterprise_facts,
            case_candidates,
            entity_context,
        )
        return SlotDeduplicationEngine.group_decisions(raw)

    @staticmethod
    def public_template_variable_decisions(
        profile: GenerationProfile,
        fallback_values: dict[str, str] | None = None,
        enterprise_facts: list[EnterpriseFact] | None = None,
        case_candidates: dict[str, CaseFactCandidate] | None = None,
        entity_context: EntityResolutionContext | None = None,
    ) -> list[dict[str, Any]]:
        return [
            SlotDeduplicationEngine.public_snapshot(item)
            for item in GenerationProfileService.template_variable_decisions(
                profile,
                fallback_values,
                enterprise_facts,
                case_candidates,
                entity_context,
            )
        ]

    @staticmethod
    def template_field_decisions(
        profile: GenerationProfile,
        fallback_values: dict[str, str] | None = None,
        enterprise_facts: list[EnterpriseFact] | None = None,
        case_candidates: dict[str, CaseFactCandidate] | None = None,
        entity_context: EntityResolutionContext | None = None,
    ) -> list[dict[str, Any]]:
        variables = GenerationProfileService.template_variable_decisions(
            profile,
            fallback_values,
            enterprise_facts,
            case_candidates,
            entity_context,
        )
        return SlotDeduplicationEngine.fan_out(variables)

    @staticmethod
    def _slot_for_field(
        key: str,
        metadata: dict[str, Any],
    ) -> DocumentSlot:
        if metadata.get("slot_id") and metadata.get("ontology_concept"):
            return DocumentSlot.from_snapshot(metadata)
        canonical_key = str(metadata.get("canonical_key") or key)
        label = (
            metadata.get("label")
            or TEMPLATE_FIELD_LABELS.get(canonical_key, canonical_key)
        )
        return SlotContextClassifier.classify(
            label=label,
            surrounding_text=metadata.get("surrounding_text") or label,
            source_location=metadata.get("source_location") or "原响应模板",
            document_section=metadata.get("document_section"),
            canonical_hint=canonical_key,
        )

    @staticmethod
    def _entity_facts(
        key: str,
        slot: DocumentSlot,
        resolution,
    ) -> list[EnterpriseFact]:
        facts: list[EnterpriseFact] = []
        if resolution.person is not None:
            values = {
                "person.name": resolution.person.name,
                "person.name_and_title": (
                    f"{resolution.person.name}/{resolution.person.title}"
                    if resolution.person.title else None
                ),
                "person.id_number": resolution.person.id_number,
                "person.title": resolution.person.title,
                "person.phone": resolution.person.phone,
            }
            value = values.get(slot.semantic_field)
            if value:
                source = (
                    resolution.person.source_documents[0]
                    if resolution.person.source_documents
                    and isinstance(
                        resolution.person.source_documents[0], dict
                    )
                    else {}
                )
                sensitivity = (
                    DataSensitivity.HIGHLY_SENSITIVE
                    if slot.semantic_field == "person.id_number"
                    else DataSensitivity.SENSITIVE
                    if slot.semantic_field == "person.phone"
                    else DataSensitivity.NORMAL
                )
                facts.append(EnterpriseFact(
                    canonical_key=key,
                    semantic_field=slot.semantic_field,
                    entity_id=str(resolution.person.id),
                    value=str(value),
                    source_type="entity_registry",
                    source_reference=str(
                        source.get("title") or "已核验人员实体"
                    ),
                    confidence=1.0,
                    verified=True,
                    sensitivity=sensitivity,
                    evidence_title=str(
                        source.get("title") or "已核验人员实体"
                    ),
                    evidence_excerpt=(
                        str(source.get("excerpt"))
                        if source.get("excerpt") else None
                    ),
                    evidence_location=(
                        str(source.get("location"))
                        if source.get("location") else None
                    ),
                ))
        if resolution.organization is not None:
            values = {
                "organization.full_name": resolution.organization.full_name,
                "organization.registered_address": (
                    resolution.organization.registered_address
                ),
            }
            value = values.get(slot.semantic_field)
            if value:
                facts.append(EnterpriseFact(
                    canonical_key=key,
                    semantic_field=slot.semantic_field,
                    entity_id=str(resolution.organization.id),
                    value=str(value),
                    source_type="entity_registry",
                    source_reference=(
                        resolution.organization.source_document
                        or "已核验企业实体"
                    ),
                    confidence=resolution.organization.confidence,
                    verified=True,
                    evidence_title=(
                        resolution.organization.source_document
                        or "已核验企业实体"
                    ),
                    evidence_location=(
                        resolution.organization.source_location
                    ),
                ))
        return facts

    @staticmethod
    def _resolution_snapshot(
        slot: DocumentSlot,
        resolution,
        context: EntityResolutionContext | None,
    ) -> dict[str, Any]:
        return {
            "slot": slot.snapshot(),
            "semantic_field": slot.semantic_field,
            "expected_entity_type": (
                slot.expected_entity_type.value
                if slot.expected_entity_type else None
            ),
            "expected_role": (
                slot.expected_role.value if slot.expected_role else None
            ),
            "expected_role_label": (
                ROLE_LABELS[slot.expected_role]
                if slot.expected_role else None
            ),
            "subject_organization": (
                context.organization.full_name
                if context and context.organization else None
            ),
            "project_name": context.project_name if context else None,
            "binding_status": (
                resolution.status
                if resolution is not None
                else "binding_required"
                if slot.expected_entity_type in {
                    EntityType.PERSON, EntityType.ORGANIZATION
                }
                else None
            ),
            "resolved_entity_type": (
                "Person"
                if (
                    slot.expected_entity_type is EntityType.PERSON
                    and resolution is not None
                    and resolution.person is not None
                )
                else "Organization"
                if (
                    slot.expected_entity_type is EntityType.ORGANIZATION
                    and resolution is not None
                    and resolution.organization is not None
                )
                else None
            ),
            "resolved_entity_id": (
                str(resolution.person.id)
                if (
                    slot.expected_entity_type is EntityType.PERSON
                    and resolution is not None
                    and resolution.person is not None
                )
                else str(resolution.organization.id)
                if (
                    slot.expected_entity_type is EntityType.ORGANIZATION
                    and resolution is not None
                    and resolution.organization is not None
                )
                else None
            ),
            "match_path": (
                list(resolution.match_path) if resolution is not None else []
            ),
            "entity_candidates": (
                [item.snapshot() for item in resolution.candidates]
                if resolution is not None else []
            ),
            "ontology_concept": slot.ontology_concept,
            "display_name": slot.display_name,
            "subject_role": (
                slot.subject_role.value if slot.subject_role else None
            ),
            "relation_path": list(slot.relation_path),
            "value_expression": slot.value_expression,
            "fill_strategy": slot.fill_strategy.value,
            "required_actions": list(slot.required_actions),
        }

    @staticmethod
    def review_template_field(
        project_id: UUID,
        field_key: str,
        action: str,
        value: str | None = None,
    ) -> GenerationProfile:
        profile = GenerationProfileService.get(project_id)
        key = field_key.strip()
        evidence: dict[str, Any] = {}
        manual_value = value.strip() if value is not None else None
        known_keys = set(ResponseTemplateService.required_fields(
            profile.template_descriptor
        )) | set(profile.template_field_values)
        if key not in known_keys:
            raise ValueError("模板字段不存在，不能新增未识别字段。")
        if manual_value and action != "confirm":
            raise ValueError("只有确认操作可以保存人工修改值。")
        field_metadata = next(
            (
                item
                for item in profile.template_descriptor.get("fields", [])
                if item.get("field_key") == key
            ),
            {},
        )
        slot = GenerationProfileService._slot_for_field(
            key, field_metadata
        )
        if manual_value and slot.fill_strategy is not FillStrategy.UNRESOLVED:
            raise ValueError(
                "已识别业务槽位不能直接输入；请从已核验数据库自动匹配，"
                "必要时先建立实体或项目角色关系。"
            )
        if manual_value and not StrictFillDecisionEngine.value_matches_field_type(
            slot.canonical_key, manual_value
        ):
            label = StrictFillDecisionEngine.field_type_label(
                slot.canonical_key
            )
            raise ValueError(f"填写内容不符合字段类型（{label}），请填写真实值。")
        if manual_value:
            previous_value = profile.template_field_values.get(key)
            values = dict(profile.template_field_values)
            values[key] = manual_value
            GenerationProfileService.update_template_fields(project_id, values)
            profile = GenerationProfileService.get(project_id)
            evidence = {
                "source_reference": "人工审核修改",
                "evidence_title": "人工审核修改",
                "evidence_excerpt": manual_value,
                "evidence_location": "当前项目人工审核",
                "evidence_match_count": 1,
                "input_method": "manual_edit",
                "previous_value": previous_value,
            }
        elif key not in profile.template_field_values:
            decisions = GenerationProfileService.template_field_decisions(
                profile,
                enterprise_facts=EnterpriseFactResolver().resolve(project_id),
                case_candidates=CaseFactResolver().resolve(project_id),
                entity_context=(
                    EntityResolutionService().resolve_project(project_id)
                ),
            )
            candidate = next(
                (
                    item for item in decisions
                    if item["field_key"] == key
                    and item["status"] == "REVIEW_REQUIRED"
                    and item["value"]
                ),
                None,
            )
            if candidate is None:
                raise ValueError("模板字段不存在或尚未匹配到候选值。")
            evidence = {
                "source_reference": candidate.get("source_reference"),
                "evidence_title": candidate.get("evidence_title"),
                "evidence_excerpt": candidate.get("evidence_excerpt"),
                "evidence_location": candidate.get("evidence_location"),
                "evidence_match_count": candidate.get("evidence_match_count", 0),
                "evidence_alternatives": candidate.get(
                    "evidence_alternatives", []
                ),
            }
            values = dict(profile.template_field_values)
            values[key] = candidate["value"]
            GenerationProfileService.update_template_fields(project_id, values)
            profile = GenerationProfileService.get(project_id)
        report = dict(profile.last_fill_report or {})
        reviews = dict(report.get("field_reviews") or {})
        if action == "confirm":
            reviews[key] = {
                "status": "confirmed",
                "value": profile.template_field_values[key],
                "reviewed_by": "current_session",
                "reviewed_at": datetime.now().astimezone().isoformat(),
                **{
                    name: evidence_value
                    for name, evidence_value in evidence.items()
                    if evidence_value
                },
            }
        elif action == "reset":
            reviews.pop(key, None)
        else:
            raise ValueError("不支持的审核操作。")
        report["field_reviews"] = reviews
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET last_fill_report = %s::jsonb, updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(report, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("方案生成档案不存在。")
        return GenerationProfileService.get(project_id)

    @staticmethod
    def review_template_variable(
        project_id: UUID,
        variable_key: str,
        action: str,
        value: str | None = None,
    ) -> GenerationProfile:
        """Review one business fact once and apply it to every bound slot."""
        profile = GenerationProfileService.get(project_id)
        variables = GenerationProfileService.template_variable_decisions(
            profile,
            enterprise_facts=EnterpriseFactResolver().resolve(project_id),
            case_candidates=CaseFactResolver().resolve(project_id),
            entity_context=EntityResolutionService().resolve_project(project_id),
        )
        variable = next(
            (
                item for item in variables
                if item.get("variable_key") == variable_key.strip()
            ),
            None,
        )
        if variable is None:
            raise ValueError("业务变量不存在或已随模板规则更新。")
        field_keys = [
            str(item.get("field_key"))
            for item in variable.get("slots", ())
            if item.get("field_key")
        ]
        if not field_keys:
            raise ValueError("业务变量没有可回填的模板位置。")
        if action not in {"confirm", "reset"}:
            raise ValueError("不支持的审核操作。")

        report = dict(profile.last_fill_report or {})
        field_reviews = dict(report.get("field_reviews") or {})
        variable_reviews = dict(report.get("variable_reviews") or {})
        if action == "reset":
            variable_reviews.pop(variable_key, None)
            for field_key in field_keys:
                field_reviews.pop(field_key, None)
        else:
            selected = str(value or variable.get("value") or "").strip()
            if not selected:
                raise ValueError(
                    "当前业务变量没有可确认值；请先补充企业事实或建立角色绑定。"
                )
            canonical_keys = {
                str(item.get("canonical_key") or "")
                for item in variable.get("_field_decisions", ())
            }
            if any(
                not StrictFillDecisionEngine.value_matches_field_type(
                    canonical_key, selected
                )
                for canonical_key in canonical_keys if canonical_key
            ):
                raise ValueError("确认内容与业务变量的数据类型不一致。")
            values = dict(profile.template_field_values)
            reviewed_at = datetime.now().astimezone().isoformat()
            evidence = {
                "source_reference": (
                    "本项目人工修正"
                    if value else variable.get("source_reference")
                ),
                "evidence_title": (
                    "本项目人工修正"
                    if value else variable.get("evidence_title")
                ),
                "evidence_excerpt": (
                    f"本项目人工修正：{selected}"
                    if value else variable.get("evidence_excerpt")
                ),
                "evidence_location": (
                    "严格回填预览人工审核"
                    if value else variable.get("evidence_location")
                ),
                "input_method": (
                    "preview_manual_override" if value else "variable_review"
                ),
            }
            for field_key in field_keys:
                values[field_key] = selected
                field_reviews[field_key] = {
                    "status": "confirmed",
                    "value": selected,
                    "reviewed_by": "current_session",
                    "reviewed_at": reviewed_at,
                    **{
                        key: item for key, item in evidence.items() if item
                    },
                }
            GenerationProfileService.update_template_fields(project_id, values)
            variable_reviews[variable_key] = {
                "status": "confirmed",
                "value": selected,
                "reviewed_by": "current_session",
                "reviewed_at": reviewed_at,
                "affected_slot_count": len(field_keys),
                **{key: item for key, item in evidence.items() if item},
            }
        report["field_reviews"] = field_reviews
        report["variable_reviews"] = variable_reviews
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET last_fill_report = %s::jsonb, updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(report, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("方案生成档案不存在。")
        return GenerationProfileService.get(project_id)

    @staticmethod
    def update_template_fields(
        project_id: UUID,
        values: dict[str, str],
    ) -> GenerationProfile:
        cleaned: dict[str, str] = {}
        for raw_key, raw_value in values.items():
            key = str(raw_key).strip()
            value = str(raw_value).strip()
            if not key or len(key) > 80 or not value or len(value) > 500:
                raise ValueError("模板字段名或字段值无效。")
            canonical_key = key.split("__", 1)[0]
            if not StrictFillDecisionEngine.value_matches_field_type(
                canonical_key, value
            ):
                label = StrictFillDecisionEngine.field_type_label(
                    canonical_key
                )
                raise ValueError(f"填写内容不符合字段类型（{label}）。")
            cleaned[key] = value
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET template_field_values = %s::jsonb,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(cleaned, ensure_ascii=False), project_id),
                )
                if cursor.rowcount == 0:
                    raise ValueError("方案生成档案不存在。")
        return GenerationProfileService.get(project_id)

    @staticmethod
    def template_path(profile: GenerationProfile) -> Path | None:
        if profile.converted_template_storage_key:
            return GenerationProfileService._safe_storage_path(
                profile.converted_template_storage_key
            )
        if not profile.template_storage_key:
            return None
        root = Path(settings.storage_root).resolve()
        path = (root / profile.template_storage_key).resolve()
        if root not in path.parents:
            raise ValueError("非法模板存储路径。")
        return path

    @staticmethod
    def _safe_storage_path(storage_key: str) -> Path:
        root = Path(settings.storage_root).resolve()
        path = (root / storage_key).resolve()
        if root not in path.parents:
            raise ValueError("非法模板存储路径。")
        return path

    @staticmethod
    def record_fill_report(project_id: UUID, report: dict[str, Any]) -> None:
        with connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE proposal_generation_profiles
                    SET last_fill_report = last_fill_report || %s::jsonb,
                        updated_at = NOW()
                    WHERE project_id = %s
                    """,
                    (json.dumps(report, ensure_ascii=False), project_id),
                )
