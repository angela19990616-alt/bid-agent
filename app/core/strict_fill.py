from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


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


@dataclass(frozen=True)
class FillDecision:
    field: TemplateField
    value: str | None
    source_type: str | None
    source_reference: str | None
    confidence: float
    status: FillStatus
    reason: str


class StrictFillDecisionEngine:
    """Makes deterministic fill decisions; it never invents enterprise facts."""

    NON_AUTHORITATIVE_FACT_SOURCES = {
        "historical_case",
        "proposal_memory",
        "generated_proposal",
    }

    def decide(
        self,
        field: TemplateField,
        facts: list[EnterpriseFact],
    ) -> FillDecision:
        candidates = [
            fact
            for fact in facts
            if (
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type not in self.NON_AUTHORITATIVE_FACT_SOURCES
            )
        ]
        if not candidates:
            reference_only = any(
                fact.canonical_key == field.canonical_key
                and fact.value.strip()
                and fact.source_type in self.NON_AUTHORITATIVE_FACT_SOURCES
                for fact in facts
            )
            return FillDecision(
                field=field,
                value=None,
                source_type=None,
                source_reference=None,
                confidence=0.0,
                status=FillStatus.MISSING,
                reason=(
                    "历史案例仅可参考写法，不能作为企业事实自动回填；"
                    "请从已授权企业数据库补充并核验。"
                    if reference_only
                    else "当前企业资料库不存在该信息，请补充后继续。"
                ),
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

        return FillDecision(
            field=field,
            value=candidate.value.strip(),
            source_type=candidate.source_type,
            source_reference=candidate.source_reference,
            confidence=candidate.confidence,
            status=status,
            reason=reason,
        )
