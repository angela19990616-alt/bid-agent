from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID


class EntityType(StrEnum):
    ORGANIZATION = "Organization"
    PERSON = "Person"
    PROJECT = "Project"


class ProjectRole(StrEnum):
    LEGAL_REPRESENTATIVE = "LEGAL_REPRESENTATIVE"
    AUTHORIZED_REPRESENTATIVE = "AUTHORIZED_REPRESENTATIVE"
    PROJECT_MANAGER = "PROJECT_MANAGER"
    TECHNICAL_LEAD = "TECHNICAL_LEAD"
    CONTACT_PERSON = "CONTACT_PERSON"
    SIGNATORY = "SIGNATORY"


ROLE_LABELS = {
    ProjectRole.LEGAL_REPRESENTATIVE: "法定代表人",
    ProjectRole.AUTHORIZED_REPRESENTATIVE: "授权代表",
    ProjectRole.PROJECT_MANAGER: "项目负责人",
    ProjectRole.TECHNICAL_LEAD: "技术负责人",
    ProjectRole.CONTACT_PERSON: "联系人",
    ProjectRole.SIGNATORY: "签字人",
}


@dataclass(frozen=True)
class Organization:
    id: UUID
    full_name: str
    unified_social_credit_code: str | None = None
    registered_address: str | None = None
    legal_representative_person_id: UUID | None = None
    source_document: str | None = None
    source_location: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class Person:
    id: UUID
    name: str
    id_number: str | None = None
    title: str | None = None
    phone: str | None = None
    phone_masked: str | None = None
    id_number_masked: str | None = None
    certificates: tuple[dict[str, Any], ...] = ()
    source_documents: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Project:
    id: UUID
    project_name: str
    project_number: str | None = None
    bidder_organization_id: UUID | None = None


@dataclass(frozen=True)
class ProjectRoleAssignment:
    project_id: UUID
    role: ProjectRole
    person_id: UUID
    organization_id: UUID
    authorization_document_id: int | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    status: str = "active"
    source_document: str | None = None
    source_location: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True)
class DocumentSlot:
    slot_id: str
    document_section: str | None
    table_index: int | None
    paragraph_index: int | None
    row: int | None
    column: int | None
    surrounding_text: str
    semantic_field: str
    canonical_key: str
    expected_entity_type: EntityType | None
    expected_role: ProjectRole | None
    expected_value_type: str
    source_requirement: str | None
    confidence: float

    @classmethod
    def from_snapshot(cls, value: dict[str, Any]) -> "DocumentSlot":
        entity_type = value.get("expected_entity_type")
        role = value.get("expected_role")
        return cls(
            slot_id=str(value.get("slot_id") or value.get("field_key") or ""),
            document_section=value.get("document_section"),
            table_index=value.get("table_index"),
            paragraph_index=value.get("paragraph_index"),
            row=value.get("row"),
            column=value.get("column"),
            surrounding_text=str(value.get("surrounding_text") or value.get("label") or ""),
            semantic_field=str(value.get("semantic_field") or "text.value"),
            canonical_key=str(value.get("canonical_key") or value.get("field_key") or ""),
            expected_entity_type=(
                EntityType(entity_type) if entity_type else None
            ),
            expected_role=ProjectRole(role) if role else None,
            expected_value_type=str(value.get("expected_value_type") or "unknown"),
            source_requirement=value.get("source_requirement"),
            confidence=float(value.get("confidence") or 0),
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "document_section": self.document_section,
            "table_index": self.table_index,
            "paragraph_index": self.paragraph_index,
            "row": self.row,
            "column": self.column,
            "surrounding_text": self.surrounding_text,
            "semantic_field": self.semantic_field,
            "canonical_key": self.canonical_key,
            "expected_entity_type": (
                self.expected_entity_type.value
                if self.expected_entity_type else None
            ),
            "expected_role": (
                self.expected_role.value if self.expected_role else None
            ),
            "expected_value_type": self.expected_value_type,
            "source_requirement": self.source_requirement,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class EntityCandidate:
    person_id: UUID
    name: str
    title: str | None
    match_basis: str
    source_document: str | None
    source_location: str | None
    confidence: float

    def snapshot(self) -> dict[str, Any]:
        return {
            "person_id": str(self.person_id),
            "name": self.name,
            "title": self.title,
            "match_basis": self.match_basis,
            "source_document": self.source_document,
            "source_location": self.source_location,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class EntityResolutionContext:
    project_id: UUID
    project_name: str | None = None
    organization: Organization | None = None
    people: tuple[Person, ...] = ()
    assignments: tuple[ProjectRoleAssignment, ...] = ()
    candidates_by_role: dict[ProjectRole, tuple[EntityCandidate, ...]] = field(
        default_factory=dict
    )

    def person(self, person_id: UUID) -> Person | None:
        return next(
            (item for item in self.people if item.id == person_id), None
        )

    def bound_person_id(
        self,
        role: ProjectRole,
    ) -> UUID | None:
        if (
            role is ProjectRole.LEGAL_REPRESENTATIVE
            and self.organization is not None
        ):
            return self.organization.legal_representative_person_id
        active = {
            item.person_id for item in self.assignments
            if item.project_id == self.project_id
            and item.role is role
            and item.status == "active"
        }
        return next(iter(active)) if len(active) == 1 else None


@dataclass(frozen=True)
class SlotResolution:
    status: str
    person: Person | None
    organization: Organization | None
    candidates: tuple[EntityCandidate, ...]
    reason: str
    match_path: tuple[str, ...]


class SlotContextClassifier:
    """Classify the whole slot context, never the word `姓名` alone."""

    ROLE_ALIASES: tuple[tuple[ProjectRole, tuple[str, ...]], ...] = (
        (
            ProjectRole.LEGAL_REPRESENTATIVE,
            ("法定代表人", "法定代表", "法人代表", "法人"),
        ),
        (
            ProjectRole.AUTHORIZED_REPRESENTATIVE,
            ("委托代理人", "授权代理人", "授权代表", "被授权人", "受托人"),
        ),
        (ProjectRole.PROJECT_MANAGER, ("项目负责人", "项目经理")),
        (ProjectRole.TECHNICAL_LEAD, ("技术负责人", "技术总监")),
        (ProjectRole.CONTACT_PERSON, ("联系人", "项目联系人")),
        (ProjectRole.SIGNATORY, ("签字人", "签署人")),
    )
    ROLE_FIELDS = {
        ProjectRole.LEGAL_REPRESENTATIVE: "legal_representative",
        ProjectRole.AUTHORIZED_REPRESENTATIVE: "authorized_representative",
        ProjectRole.PROJECT_MANAGER: "project_manager_name",
        ProjectRole.TECHNICAL_LEAD: "technical_lead_name",
        ProjectRole.CONTACT_PERSON: "contact_person",
        ProjectRole.SIGNATORY: "signatory_name",
    }
    EXPLICIT_NON_PERSON_KEYS = {
        "project_name", "project_number", "bidder_name",
        "registered_address", "postal_code", "enterprise_qualification",
        "bank_account", "bid_round", "date", "fax", "website",
    }

    @classmethod
    def classify(
        cls,
        *,
        label: str,
        surrounding_text: str,
        source_location: str,
        document_section: str | None = None,
        table_index: int | None = None,
        paragraph_index: int | None = None,
        row: int | None = None,
        column: int | None = None,
        canonical_hint: str | None = None,
    ) -> DocumentSlot:
        context = re.sub(
            r"\s+", "", f"{document_section or ''}{surrounding_text}{label}"
        )
        role_matches = {
            role for role, aliases in cls.ROLE_ALIASES
            if any(cls._role_alias_matches(context, role, alias) for alias in aliases)
        }
        if "委托" in context and "代理人" in context:
            role_matches.add(ProjectRole.AUTHORIZED_REPRESENTATIVE)
        role = next(iter(role_matches)) if len(role_matches) == 1 else None
        compact_label = re.sub(r"\s+", "", label)
        organization_field = bool(
            re.search(r"投标人|供应商|响应人|单位|企业", compact_label)
            and re.search(r"名称|全称", compact_label)
        )
        if organization_field:
            canonical_key = "bidder_name"
            semantic_field = "organization.full_name"
            entity_type = EntityType.ORGANIZATION
            value_type = "organization_name"
            confidence = 0.96
        elif canonical_hint in cls.EXPLICIT_NON_PERSON_KEYS:
            canonical_key, semantic_field, entity_type, value_type = (
                cls._non_person_field(label, context, canonical_hint)
            )
            role = None
            confidence = 0.96
        elif role is not None:
            if re.search(r"身份证(?:号码|号)", compact_label):
                canonical_key = "person_id_number"
                semantic_field = "person.id_number"
                value_type = "identity_number"
            elif re.search(r"职务|职位|岗位", compact_label):
                canonical_key = "person_title"
                semantic_field = "person.title"
                value_type = "job_title"
            elif re.search(r"电话|手机|联系方式", compact_label):
                canonical_key = "contact_phone"
                semantic_field = "person.phone"
                value_type = "phone"
            else:
                canonical_key = cls.ROLE_FIELDS[role]
                semantic_field = "person.name"
                value_type = "person_name"
            entity_type = EntityType.PERSON
            confidence = 0.98 if re.search(
                r"姓名|名称|代表|代理人|负责人|联系人|身份证|职务|职位|电话|手机",
                compact_label,
            ) else 0.86
        elif len(role_matches) > 1 and re.search(
            r"姓名|代表|代理人|负责人|联系人", compact_label
        ):
            canonical_key = "person_name"
            semantic_field = "person.name"
            entity_type = EntityType.PERSON
            value_type = "person_name"
            confidence = 0.55
        else:
            canonical_key, semantic_field, entity_type, value_type = (
                cls._non_person_field(label, context, canonical_hint)
            )
            confidence = 0.82 if canonical_key else 0.55
            canonical_key = canonical_key or "custom_" + hashlib.sha256(
                f"{source_location}|{label}".encode()
            ).hexdigest()[:12]
        slot_id = hashlib.sha256(
            f"{source_location}|{label}|{surrounding_text}".encode()
        ).hexdigest()[:20]
        return DocumentSlot(
            slot_id=slot_id,
            document_section=document_section,
            table_index=table_index,
            paragraph_index=paragraph_index,
            row=row,
            column=column,
            surrounding_text=re.sub(r"\s+", " ", surrounding_text).strip(),
            semantic_field=semantic_field,
            canonical_key=canonical_key,
            expected_entity_type=entity_type,
            expected_role=role,
            expected_value_type=value_type,
            source_requirement=(
                re.sub(r"\s+", " ", surrounding_text).strip() or None
            ),
            confidence=confidence,
        )

    @staticmethod
    def _role_alias_matches(
        context: str,
        role: ProjectRole,
        alias: str,
    ) -> bool:
        if role is ProjectRole.CONTACT_PERSON and alias == "联系人":
            return bool(re.search(r"联系人(?!电话|手机|方式)", context))
        return alias in context

    @staticmethod
    def _non_person_field(
        label: str,
        context: str,
        canonical_hint: str | None,
    ) -> tuple[str | None, str, EntityType | None, str]:
        mappings = (
            ("project_number", "project.project_number", EntityType.PROJECT, "project_identifier", ("项目编号", "采购编号", "招标编号")),
            ("project_name", "project.project_name", EntityType.PROJECT, "project_name", ("项目名称", "采购项目名称", "招标项目名称")),
            ("registered_address", "organization.registered_address", EntityType.ORGANIZATION, "address", ("注册地址", "地址")),
            ("contact_phone", "person.phone", EntityType.PERSON, "phone", ("联系电话", "手机", "电话")),
            ("postal_code", "organization.postal_code", EntityType.ORGANIZATION, "postal_code", ("邮政编码", "邮编")),
        )
        combined = f"{label}{context}"
        for key, semantic, entity_type, value_type, aliases in mappings:
            if any(alias in combined for alias in aliases):
                return key, semantic, entity_type, value_type
        if canonical_hint:
            semantic_by_key = {
                "bidder_name": ("organization.full_name", EntityType.ORGANIZATION),
                "registered_address": ("organization.registered_address", EntityType.ORGANIZATION),
                "postal_code": ("organization.postal_code", EntityType.ORGANIZATION),
                "project_name": ("project.project_name", EntityType.PROJECT),
                "project_number": ("project.project_number", EntityType.PROJECT),
                "contact_person": ("person.name", EntityType.PERSON),
                "contact_phone": ("person.phone", EntityType.PERSON),
            }
            semantic, entity_type = semantic_by_key.get(
                canonical_hint, (f"field.{canonical_hint}", None)
            )
            from app.core.field_semantics import FieldSemanticClassifier

            return (
                canonical_hint,
                semantic,
                entity_type,
                FieldSemanticClassifier.expected_type(canonical_hint).value,
            )
        return None, "text.value", None, "unknown"


class EntityResolutionEngine:
    PROJECT_SCOPED_ROLES = {
        ProjectRole.AUTHORIZED_REPRESENTATIVE,
        ProjectRole.PROJECT_MANAGER,
        ProjectRole.TECHNICAL_LEAD,
        ProjectRole.CONTACT_PERSON,
        ProjectRole.SIGNATORY,
    }

    def resolve(
        self,
        slot: DocumentSlot,
        context: EntityResolutionContext,
    ) -> SlotResolution:
        if slot.expected_entity_type is EntityType.ORGANIZATION:
            if context.organization is None:
                return SlotResolution(
                    "missing_organization", None, None, (),
                    "当前项目尚未绑定投标主体。",
                    ("槽位识别为组织属性", "等待绑定当前投标人"),
                )
            return SlotResolution(
                "resolved", None, context.organization, (),
                "已绑定当前项目投标主体。",
                ("槽位识别为组织属性", "命中当前项目投标人"),
            )
        if slot.expected_entity_type is not EntityType.PERSON:
            return SlotResolution(
                "not_entity_bound", None, context.organization, (),
                "该字段不需要人员角色绑定。", ("按字段语义处理",),
            )
        role = slot.expected_role
        if role is None:
            return SlotResolution(
                "role_unresolved", None, context.organization, (),
                "未能根据完整句子确定人员角色，需要人工复核。",
                ("槽位识别为人员属性", "角色未确定"),
            )
        person_id = context.bound_person_id(role)
        person = context.person(person_id) if person_id else None
        candidates = context.candidates_by_role.get(role, ())
        if person is None:
            scope = (
                "企业与法定代表人的绑定"
                if role is ProjectRole.LEGAL_REPRESENTATIVE
                else f"本项目{ROLE_LABELS[role]}"
            )
            return SlotResolution(
                "binding_required", None, context.organization, candidates,
                f"尚未建立{scope}，系统不会随机选择人员。",
                (
                    f"槽位角色：{ROLE_LABELS[role]}",
                    "检查角色绑定",
                    "未获得唯一有效 person_id",
                ),
            )
        return SlotResolution(
            "resolved", person, context.organization, candidates,
            f"已通过{ROLE_LABELS[role]}绑定确定唯一人员。",
            (
                f"槽位角色：{ROLE_LABELS[role]}",
                "命中唯一有效角色绑定",
                "读取同一 person_id 的属性和附件",
            ),
        )
