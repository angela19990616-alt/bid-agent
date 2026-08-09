from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.field_semantics import FieldSemanticClassifier


class FillStatus(StrEnum):
    AUTO_FILL = "AUTO_FILL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    MISSING = "MISSING"


class DataSensitivity(StrEnum):
    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"


@dataclass(frozen=True)
class TemplateField:
    field_id: str
    label: str
    canonical_key: str
    required: bool
    source_location: str


@dataclass(frozen=True)
class EnterpriseFact:
    canonical_key: str
    value: str
    source_type: str
    source_reference: str
    confidence: float
    verified: bool
    sensitivity: DataSensitivity = DataSensitivity.NORMAL
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None


@dataclass(frozen=True)
class FillDecision:
    field: TemplateField
    value: str | None
    source_type: str | None
    source_reference: str | None
    confidence: float
    status: FillStatus
    reason: str
    evidence_title: str | None = None
    evidence_excerpt: str | None = None
    evidence_location: str | None = None


class StrictFillDecisionEngine:
    """Makes deterministic fill decisions; it never invents enterprise facts."""

    NON_AUTHORITATIVE_FACT_SOURCES = {
        "historical_case",
        "proposal_memory",
        "generated_proposal",
    }
    EVIDENCE_REQUIRED_SOURCES = {"company_profile", "qualification"}
    PERSON_FIELDS = {
        "legal_representative", "authorized_representative", "contact_person",
    }

    @classmethod
    def field_type(cls, canonical_key: str) -> str:
        return FieldSemanticClassifier.expected_type(canonical_key).value

    @classmethod
    def field_type_label(cls, canonical_key: str) -> str:
        return FieldSemanticClassifier.expected_label(canonical_key)

    @classmethod
    def value_matches_field_type(cls, canonical_key: str, value: str) -> bool:
        """Compare the candidate's semantic type with the field contract."""
        return FieldSemanticClassifier.matches(canonical_key, value)

    def decide(
        self,
        field: TemplateField,
        facts: list[EnterpriseFact],
    ) -> FillDecision:
        authoritative = [
            fact
            for fact in facts
            if (
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type not in self.NON_AUTHORITATIVE_FACT_SOURCES
            )
        ]
        candidates = [
            fact for fact in authoritative
            if self.value_matches_field_type(field.canonical_key, fact.value)
        ]
        if not candidates:
            reference_only = any(
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type in self.NON_AUTHORITATIVE_FACT_SOURCES
                for fact in facts
            )
            if authoritative:
                missing_reason = "匹配内容不符合字段类型，已拒绝自动回填。"
            elif reference_only:
                missing_reason = (
                    "历史案例仅可参考写法，不能作为企业事实自动回填；"
                    "请从已授权企业数据库补充并核验。"
                )
            else:
                missing_reason = "当前企业资料库不存在该信息，请补充后继续。"
            return FillDecision(
                field=field,
                value=None,
                source_type=None,
                source_reference=None,
                confidence=0.0,
                status=FillStatus.MISSING,
                reason=missing_reason,
            )

        distinct_values = {fact.value.strip() for fact in candidates}
        if len(distinct_values) > 1:
            return FillDecision(
                field=field,
                value=None,
                source_type=None,
                source_reference=None,
                confidence=max(fact.confidence for fact in candidates),
                status=FillStatus.REVIEW_REQUIRED,
                reason="企业资料库存在多个不同值，需要人工确认采用口径。",
            )

        candidate = max(
            candidates,
            key=lambda fact: (fact.verified, fact.confidence),
        )
        status = FillStatus.AUTO_FILL
        reason = "来源已核验，可以自动回填。"
        if not candidate.verified or candidate.confidence < 1.0:
            status = FillStatus.REVIEW_REQUIRED
            reason = "数据尚未完成权威核验，需要人工确认。"
        if candidate.sensitivity != DataSensitivity.NORMAL:
            status = FillStatus.REVIEW_REQUIRED
            reason = "该字段属于受控敏感数据，授权审核后方可回填。"
        if (
            candidate.source_type in self.EVIDENCE_REQUIRED_SOURCES
            and not candidate.evidence_location
        ):
            status = FillStatus.REVIEW_REQUIRED
            reason = "企业事实已匹配，但来源记录缺少页码、章节或附件位置，需要人工复核。"

        return FillDecision(
            field=field,
            value=candidate.value.strip(),
            source_type=candidate.source_type,
            source_reference=candidate.source_reference,
            confidence=candidate.confidence,
            status=status,
            reason=reason,
            evidence_title=candidate.evidence_title,
            evidence_excerpt=candidate.evidence_excerpt,
            evidence_location=candidate.evidence_location,
        )
