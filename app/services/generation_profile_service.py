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


TEMPLATE_FIELD_LABELS = {
    "project_name": "项目名称",
    "project_number": "项目编号",
    "bidder_name": "供应商名称",
    "legal_representative": "法定代表人",
    "authorized_representative": "授权代表",
    "date": "日期",
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


class GenerationProfileService:
    def __init__(self, template_service: ResponseTemplateService | None = None):
        self.template_service = template_service or ResponseTemplateService()

    def inspect_document(
        self,
        *,
        project_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
    ) -> GenerationProfile:
        descriptor = self.template_service.detect(filename, content)
        source_fields = self.template_service.extract_source_fields(
            filename, content
        )
        mode = self.mode_for_descriptor(descriptor.snapshot())
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
                cursor.execute(
                    """
                    INSERT INTO proposal_generation_profiles (
                        project_id, generation_mode, template_document_id,
                        template_descriptor, template_field_values
                    )
                    VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
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
                        updated_at = NOW()
                    """,
                    (
                        project_id,
                        mode,
                        document["id"] if descriptor.detected else None,
                        json.dumps(descriptor.snapshot(), ensure_ascii=False),
                        json.dumps(source_fields, ensure_ascii=False),
                    ),
                )
        return self.get(project_id)

    @staticmethod
    def mode_for_descriptor(descriptor: dict[str, Any]) -> str:
        if descriptor.get("detected") and descriptor.get("source_format") == "docx":
            return "strict_template"
        if descriptor.get("detected") and descriptor.get("source_format") == "pdf":
            return "pdf_template_manual_fill"
        return "planned"

    @staticmethod
    def preferred_mode(existing: str, incoming: str) -> str:
        priority = {
            "planned": 1,
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
            )
        return GenerationProfile(**row)

    @staticmethod
    def template_field_decisions(
        profile: GenerationProfile,
        fallback_values: dict[str, str] | None = None,
        enterprise_facts: list[EnterpriseFact] | None = None,
        case_candidates: dict[str, CaseFactCandidate] | None = None,
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
            value = (
                profile.template_field_values.get(key)
                or fallback_values.get(key)
                or ""
            ).strip()
            facts: list[EnterpriseFact] = [
                fact
                for fact in (enterprise_facts or [])
                if fact.canonical_key == key
            ]
            if value:
                review = reviews.get(key, {})
                confirmed = (
                    review.get("status") == "confirmed"
                    and review.get("value") == value
                )
                procurement_fact = key in {"project_name", "project_number"}
                metadata = field_metadata.get(key, {})
                expected_source = metadata.get("expected_source")
                facts.append(EnterpriseFact(
                    canonical_key=key,
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
                    sensitivity=(
                        DataSensitivity.SENSITIVE
                        if (
                            expected_source == "controlled_personnel_vault"
                            and not confirmed
                        )
                        else DataSensitivity.NORMAL
                    ),
                ))
            metadata = field_metadata.get(key, {})
            field = TemplateField(
                field_id=key,
                label=metadata.get("label") or TEMPLATE_FIELD_LABELS.get(key, key),
                canonical_key=key,
                required=key in required,
                source_location=metadata.get("source_location") or "原响应模板",
            )
            decision = engine.decide(field, facts)
            candidate = (case_candidates or {}).get(key)
            if decision.status.value == "MISSING" and candidate is not None:
                decisions.append({
                    "field_key": key,
                    "label": field.label,
                    "value": candidate.value,
                    "source_type": "historical_case",
                    "source_reference": candidate.source_title,
                    "confidence": candidate.confidence,
                    "status": "REVIEW_REQUIRED",
                    "reason": "从五份机构私有案例中匹配到候选值，确认后才可用于正式交付。",
                    "required": field.required,
                    "evidence_title": candidate.source_title,
                    "evidence_excerpt": candidate.source_excerpt,
                    "evidence_location": "机构私有案例库",
                    "evidence_match_count": candidate.match_count,
                })
                continue
            decisions.append({
                "field_key": key,
                "label": field.label,
                "value": decision.value,
                "source_type": decision.source_type,
                "source_reference": decision.source_reference,
                "confidence": decision.confidence,
                "status": decision.status.value,
                "reason": decision.reason,
                "required": field.required,
                "evidence_title": (
                    reviews.get(key, {}).get("evidence_title")
                    or decision.source_reference
                ),
                "evidence_excerpt": reviews.get(key, {}).get(
                    "evidence_excerpt"
                ),
                "evidence_location": (
                    reviews.get(key, {}).get("evidence_location")
                    or decision.source_type
                ),
                "evidence_match_count": reviews.get(key, {}).get(
                    "evidence_match_count", 1 if decision.value else 0
                ),
            })
        return decisions

    @staticmethod
    def review_template_field(
        project_id: UUID,
        field_key: str,
        action: str,
    ) -> GenerationProfile:
        profile = GenerationProfileService.get(project_id)
        key = field_key.strip()
        evidence: dict[str, Any] = {}
        if key not in profile.template_field_values:
            decisions = GenerationProfileService.template_field_decisions(
                profile,
                enterprise_facts=EnterpriseFactResolver().resolve(project_id),
                case_candidates=CaseFactResolver().resolve(project_id),
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
                **{name: value for name, value in evidence.items() if value},
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
        if not profile.template_storage_key:
            return None
        root = Path(settings.storage_root).resolve()
        path = (root / profile.template_storage_key).resolve()
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
