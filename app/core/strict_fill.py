from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.field_semantics import FieldSemanticClassifier
from app.core.entity_resolution import EntityType, SlotResolution


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
    semantic_field: str | None = None
    expected_entity_type: str | None = None
    expected_role: str | None = None
    slot_id: str | None = None
    surrounding_text: str | None = None


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
    entity_id: str | None = None
    semantic_field: str | None = None


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
    binding_status: str | None = None
    match_path: tuple[str, ...] = ()


class StrictFillDecisionEngine:
    """Makes deterministic fill decisions; it never invents enterprise facts."""

    NON_AUTHORITATIVE_FACT_SOURCES = {
        "historical_case",
        "proposal_memory",
        "generated_proposal",
    }
    EVIDENCE_REQUIRED_SOURCES = {
        "company_profile", "qualification", "entity_registry",
    }
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
        entity_resolution: SlotResolution | None = None,
    ) -> FillDecision:
        if field.expected_entity_type in {
            EntityType.PERSON.value, EntityType.ORGANIZATION.value,
        }:
            if entity_resolution is None or entity_resolution.status != "resolved":
                reason = (
                    entity_resolution.reason
                    if entity_resolution is not None
                    else (
                        "该人员字段尚未完成角色绑定，系统不会按姓名随机匹配。"
                        if field.expected_entity_type == EntityType.PERSON.value
                        else "该组织字段尚未绑定当前投标主体，系统不会按名称模糊匹配。"
                    )
                )
                return FillDecision(
                    field=field,
                    value=None,
                    source_type=None,
                    source_reference=None,
                    confidence=0.0,
                    status=FillStatus.MISSING,
                    reason=reason,
                    binding_status=(
                        entity_resolution.status
                        if entity_resolution is not None
                        else "binding_required"
                    ),
                    match_path=(
                        entity_resolution.match_path
                        if entity_resolution is not None else ()
                    ),
                )
            if field.expected_entity_type == EntityType.PERSON.value:
                target_entity_id = (
                    str(entity_resolution.person.id)
                    if entity_resolution.person is not None else None
                )
            else:
                target_entity_id = (
                    str(entity_resolution.organization.id)
                    if entity_resolution.organization is not None else None
                )
        else:
            target_entity_id = None
        authoritative = [
            fact
            for fact in facts
            if (
                (
                    fact.canonical_key == field.canonical_key
                    or (
                        field.semantic_field
                        and fact.semantic_field == field.semantic_field
                    )
                )
                and (
                    target_entity_id is None
                    or fact.entity_id == target_entity_id
                )
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
                binding_status=(
                    entity_resolution.status
                    if entity_resolution is not None else None
                ),
                match_path=(
                    entity_resolution.match_path
                    if entity_resolution is not None else ()
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
                binding_status=(
                    entity_resolution.status
                    if entity_resolution is not None else None
                ),
                match_path=(
                    entity_resolution.match_path
                    if entity_resolution is not None else ()
                ),
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
            binding_status=(
                entity_resolution.status
                if entity_resolution is not None else None
            ),
            match_path=(
                entity_resolution.match_path
                if entity_resolution is not None else ()
            ),
        )
