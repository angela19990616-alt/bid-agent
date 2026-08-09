from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID


class EntityType(StrEnum):
    ORGANIZATION = "Organization"
    PERSON = "Person"
    PROJECT = "Project"
    BUSINESS_CASE = "BusinessCase"
    CERTIFICATE = "Certificate"
    RESPONSE_ITEM = "ResponseItem"


class SubjectRole(StrEnum):
    CURRENT_PROJECT = "CURRENT_PROJECT"
    BIDDER_ORGANIZATION = "BIDDER_ORGANIZATION"
    CONSORTIUM_LEAD = "CONSORTIUM_LEAD"
    CONSORTIUM_MEMBER = "CONSORTIUM_MEMBER"
    BID_RESPONSE_DOCUMENT = "BID_RESPONSE_DOCUMENT"
    DOCUMENT_ACTION = "DOCUMENT_ACTION"
    BUSINESS_CASE_LIBRARY = "BUSINESS_CASE_LIBRARY"
    CERTIFICATE_LIBRARY = "CERTIFICATE_LIBRARY"
    RESPONSE_TABLE = "RESPONSE_TABLE"
    DOCUMENT_LAYOUT = "DOCUMENT_LAYOUT"


class FillStrategy(StrEnum):
    DIRECT_ATTRIBUTE = "direct_attribute"
    COMPOSED_VALUE = "composed_value"
    ACTION_ONLY = "action_only"
    AUTO_LAYOUT = "auto_layout"
    GENERATED_COLLECTION = "generated_collection"
    KNOWLEDGE_COLLECTION = "knowledge_collection"
    UNRESOLVED = "unresolved"


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
    employment_history: tuple[dict[str, Any], ...] = ()
    role_history: tuple[dict[str, Any], ...] = ()
    certification_history: tuple[dict[str, Any], ...] = ()
    project_participation: tuple[dict[str, Any], ...] = ()


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
    source_location: str
    semantic_field: str
    canonical_key: str
    expected_entity_type: EntityType | None
    expected_role: ProjectRole | None
    expected_value_type: str
    source_requirement: str | None
    confidence: float
    ontology_concept: str = "unmapped"
    display_name: str = "待识别字段"
    subject_role: SubjectRole | None = None
    relation_path: tuple[str, ...] = ()
    value_expression: str | None = None
    fill_strategy: FillStrategy = FillStrategy.UNRESOLVED
    required_actions: tuple[str, ...] = ()

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
            source_location=str(value.get("source_location") or "原响应模板"),
            semantic_field=str(value.get("semantic_field") or "text.value"),
            canonical_key=str(value.get("canonical_key") or value.get("field_key") or ""),
            expected_entity_type=(
                EntityType(entity_type) if entity_type else None
            ),
            expected_role=ProjectRole(role) if role else None,
            expected_value_type=str(value.get("expected_value_type") or "unknown"),
            source_requirement=value.get("source_requirement"),
            confidence=float(value.get("confidence") or 0),
            ontology_concept=str(value.get("ontology_concept") or "unmapped"),
            display_name=str(value.get("display_name") or value.get("label") or "待识别字段"),
            subject_role=(
                SubjectRole(value["subject_role"])
                if value.get("subject_role") else None
            ),
            relation_path=tuple(value.get("relation_path") or ()),
            value_expression=value.get("value_expression"),
            fill_strategy=FillStrategy(
                value.get("fill_strategy") or FillStrategy.UNRESOLVED.value
            ),
            required_actions=tuple(value.get("required_actions") or ()),
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
            "source_location": self.source_location,
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
            "ontology_concept": self.ontology_concept,
            "display_name": self.display_name,
            "subject_role": (
                self.subject_role.value if self.subject_role else None
            ),
            "relation_path": list(self.relation_path),
            "value_expression": self.value_expression,
            "fill_strategy": self.fill_strategy.value,
            "required_actions": list(self.required_actions),
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

    @staticmethod
    @lru_cache(maxsize=1)
    def _ontology() -> dict[str, Any]:
        path = (
            Path(__file__).resolve().parents[2]
            / "config" / "rules" / "strict_fill_ontology.default.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def ontology_version(cls) -> str:
        return str(cls._ontology().get("version") or "unknown")

    @classmethod
    def _configured_role_aliases(
        cls,
    ) -> tuple[tuple[ProjectRole, tuple[str, ...]], ...]:
        configured = cls._ontology().get("roles", {})
        return tuple(
            (
                ProjectRole(role),
                tuple(str(item) for item in details.get("aliases", ())),
            )
            for role, details in configured.items()
        ) or cls.ROLE_ALIASES

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
        slot_context = re.sub(r"\s+", "", f"{surrounding_text}{label}")
        context = re.sub(
            r"\s+", "", f"{document_section or ''}{slot_context}"
        )
        role_matches = {
            role for role, aliases in cls._configured_role_aliases()
            if any(
                cls._role_alias_matches(slot_context, role, alias)
                for alias in aliases
            )
        }
        if not role_matches:
            role_matches = {
                role for role, aliases in cls._configured_role_aliases()
                if any(
                    cls._role_alias_matches(context, role, alias)
                    for alias in aliases
                )
            }
        person_value_slot = bool(re.search(
            r"姓名|身份证|职务|职位|电话|手机|代表|代理人|负责人|联系人",
            label,
        ))
        marker_index = slot_context.find("【当前空位")
        nearest_role = cls._nearest_role(slot_context, marker_index)
        if person_value_slot and nearest_role is not None:
            role_matches = {nearest_role}
        # Resolve the relationship nearest to the blank.  An authorization
        # sentence commonly mentions both the legal representative and the
        # agent; the verb phrase around the blank is authoritative.
        elif person_value_slot and re.search(
            r"(?:现|兹)?委托.{0,18}(?:姓名|代理人)", slot_context,
        ):
            role_matches = {ProjectRole.AUTHORIZED_REPRESENTATIVE}
        elif person_value_slot and re.search(
            r"(?:本人.{0,18}姓名.{0,36}(?:系|为).{0,36}法定代表人|"
            r"法定代表人.{0,12}(?:姓名|身份证|职务|电话))",
            slot_context,
        ):
            role_matches = {ProjectRole.LEGAL_REPRESENTATIVE}
        role = next(iter(role_matches)) if len(role_matches) == 1 else None
        # A standalone contact phone still belongs to the current project's
        # contact person. Do not turn this clear slot into a generic Person
        # question merely because the adjacent label omits the word “联系人”.
        if role is None and canonical_hint == "contact_phone":
            role = ProjectRole.CONTACT_PERSON
        compact_label = re.sub(r"\s+", "", label)
        required_actions = cls._required_actions(
            f"{compact_label}{surrounding_text}", role=role
        )
        if cls._is_action_only(compact_label):
            return cls._build_slot(
                label=label,
                surrounding_text=surrounding_text,
                source_location=source_location,
                document_section=document_section,
                table_index=table_index,
                paragraph_index=paragraph_index,
                row=row,
                column=column,
                semantic_field="document.action",
                canonical_key="document_action",
                entity_type=None,
                role=None,
                value_type="action",
                confidence=0.99,
                ontology_concept="BidResponseDocument.requires_action",
                display_name=(required_actions[0] if required_actions else "文档签章动作"),
                subject_role=SubjectRole.DOCUMENT_ACTION,
                relation_path=("当前项目", "投标文件", required_actions[0] if required_actions else "签章动作"),
                value_expression=None,
                fill_strategy=FillStrategy.ACTION_ONLY,
                required_actions=required_actions,
            )
        structured_table_slot = cls._structured_table_slot(
            compact_label, context
        ) if table_index is not None else None
        if structured_table_slot is not None:
            (
                canonical_key, semantic_field, entity_type, value_type,
                ontology_concept, display_name, subject_role,
                relation_path, fill_strategy,
            ) = structured_table_slot
            role = None
            confidence = 0.96
            value_expression = None
        else:
            organization_field = bool(
                re.search(
                    r"投标人|供应商|响应人|单位|企业|联合体",
                    compact_label,
                )
                and re.search(r"名称|全称", compact_label)
            )
        if structured_table_slot is not None:
            pass
        elif organization_field:
            canonical_key = "bidder_name"
            semantic_field = "organization.full_name"
            entity_type = EntityType.ORGANIZATION
            value_type = "organization_name"
            confidence = 0.96
            role = None
            subject_role = cls._organization_subject_role(context)
            ontology_concept = f"Organization[{subject_role.value}].full_name"
            display_name = (
                "当前项目投标人名称"
                if subject_role is SubjectRole.BIDDER_ORGANIZATION
                else f"{cls._subject_role_label(subject_role)}名称"
            )
            relation_path = (
                "当前项目", cls._subject_role_label(subject_role), "企业全称"
            )
            value_expression = (
                "current_project.bidder.full_name"
                if subject_role is SubjectRole.BIDDER_ORGANIZATION
                else None
            )
            fill_strategy = FillStrategy.DIRECT_ATTRIBUTE
        elif canonical_hint in cls.EXPLICIT_NON_PERSON_KEYS:
            canonical_key, semantic_field, entity_type, value_type = (
                cls._non_person_field(label, context, canonical_hint)
            )
            role = None
            confidence = 0.96
            (
                ontology_concept, display_name, subject_role,
                relation_path, value_expression, fill_strategy,
            ) = cls._non_person_ontology(canonical_key)
        elif aggregate := cls._aggregate_staffing_slot(
            compact_label, surrounding_text
        ):
            (
                canonical_key, semantic_field, entity_type, value_type,
                ontology_concept, display_name, subject_role,
                relation_path,
            ) = aggregate
            role = None
            confidence = 0.94
            value_expression = None
            fill_strategy = FillStrategy.UNRESOLVED
        elif role is not None:
            if re.search(r"身份证(?:号码|号)", compact_label):
                canonical_key = "person_id_number"
                semantic_field = "person.id_number"
                value_type = "identity_number"
            elif re.search(r"技术职称|职称", compact_label):
                canonical_key = "person_professional_title"
                semantic_field = "person.professional_title"
                value_type = "professional_title"
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
            attribute_label = cls._attribute_label(semantic_field)
            display_name = f"{ROLE_LABELS[role]}{attribute_label}"
            ontology_concept = f"Person[{role.value}].{semantic_field.rsplit('.', 1)[-1]}"
            subject_role = (
                SubjectRole.BIDDER_ORGANIZATION
                if role is ProjectRole.LEGAL_REPRESENTATIVE
                else SubjectRole.CURRENT_PROJECT
            )
            relation_path = (
                "当前项目", "投标人", ROLE_LABELS[role], attribute_label
            ) if role is ProjectRole.LEGAL_REPRESENTATIVE else (
                "当前项目", ROLE_LABELS[role], attribute_label
            )
            value_expression = (
                f"current_project.bidder.legal_representative.{semantic_field.rsplit('.', 1)[-1]}"
                if role is ProjectRole.LEGAL_REPRESENTATIVE
                else f"current_project.roles.{role.value}.{semantic_field.rsplit('.', 1)[-1]}"
            )
            fill_strategy = FillStrategy.DIRECT_ATTRIBUTE
        elif len(role_matches) > 1 and re.search(
            r"姓名|代表|代理人|负责人|联系人", compact_label
        ):
            canonical_key = "person_name"
            semantic_field = "person.name"
            entity_type = EntityType.PERSON
            value_type = "person_name"
            confidence = 0.55
            ontology_concept = "Person[AMBIGUOUS_ROLE].name"
            display_name = "角色尚未确定的人员姓名"
            subject_role = SubjectRole.CURRENT_PROJECT
            relation_path = ("当前项目", "待确认人员角色", "姓名")
            value_expression = None
            fill_strategy = FillStrategy.UNRESOLVED
        elif generic := cls._generic_business_slot(compact_label):
            (
                canonical_key, semantic_field, entity_type, value_type,
                ontology_concept, display_name, subject_role,
                relation_path,
            ) = generic
            confidence = 0.9
            value_expression = None
            fill_strategy = FillStrategy.UNRESOLVED
        else:
            canonical_key, semantic_field, entity_type, value_type = (
                cls._non_person_field(label, context, canonical_hint)
            )
            confidence = 0.82 if canonical_key else 0.55
            canonical_key = canonical_key or "unmapped_field"
            (
                ontology_concept, display_name, subject_role,
                relation_path, value_expression, fill_strategy,
            ) = cls._non_person_ontology(canonical_key)
        return cls._build_slot(
            label=label,
            surrounding_text=surrounding_text,
            source_location=source_location,
            document_section=document_section,
            table_index=table_index,
            paragraph_index=paragraph_index,
            row=row,
            column=column,
            semantic_field=semantic_field,
            canonical_key=canonical_key,
            entity_type=entity_type,
            role=role,
            value_type=value_type,
            confidence=confidence,
            ontology_concept=ontology_concept,
            display_name=display_name,
            subject_role=subject_role,
            relation_path=relation_path,
            value_expression=value_expression,
            fill_strategy=fill_strategy,
            required_actions=required_actions,
        )

    @staticmethod
    def _structured_table_slot(
        label: str,
        context: str,
    ) -> tuple[
        str, str, EntityType | None, str, str, str,
        SubjectRole | None, tuple[str, ...], FillStrategy,
    ] | None:
        """Map a grid cell to its row entity or system-managed table task.

        Empty Word table cells are not independent business facts.  A bid
        form normally represents a collection of cases, people, certificates
        or response rows.  Keeping that upper-level object prevents dozens of
        physical cells from becoming dozens of manual review questions.
        """
        normalized = re.sub(r"\s+", "", label).strip("：:")
        compact_context = re.sub(r"\s+", "", context)

        if normalized == "序号":
            return (
                "table_sequence_number", "bid_response.layout.sequence_number",
                None, "sequence_number", "BidResponseDocument.Table.sequence",
                "表格序号（系统自动编排）", SubjectRole.DOCUMENT_LAYOUT,
                ("当前项目", "投标文件", "原模板表格", "自动编排序号"),
                FillStrategy.AUTO_LAYOUT,
            )

        response_columns = {
            "磋商文件条款描述": ("requirement_text", "采购文件条款"),
            "谈判文件条款描述": ("requirement_text", "采购文件条款"),
            "采购文件条款描述": ("requirement_text", "采购文件条款"),
            "响应供应商响应描述": ("response_text", "投标响应内容"),
            "响应人响应描述": ("response_text", "投标响应内容"),
            "偏离情况说明": ("deviation_status", "偏离情况"),
            "偏离情况说明（正偏离/完全响应/负偏离）": (
                "deviation_status", "偏离情况"
            ),
            "查阅/证明文件指引": ("evidence_reference", "证明材料指引"),
            "查阅/指引": ("evidence_reference", "证明材料指引"),
        }
        if normalized in response_columns:
            attribute, display = response_columns[normalized]
            return (
                f"response_item_{attribute}",
                f"bid_response.response_item.{attribute}",
                EntityType.RESPONSE_ITEM, attribute,
                f"ResponseItem.{attribute}", display,
                SubjectRole.RESPONSE_TABLE,
                ("当前项目", "投标文件", "响应表", display),
                FillStrategy.GENERATED_COLLECTION,
            )

        case_table = (
            "用户/业主名称" in compact_context
            and any(item in compact_context for item in (
                "合同总价", "签订时间", "完成时间", "项目内容",
            ))
        )
        case_attributes = {
            "用户/业主名称": ("client_name", "客户名称"),
            "项目名称": ("project_name", "项目名称"),
            "项目内容": ("service_content", "服务内容"),
            "合同总价": ("contract_amount", "合同金额"),
            "签订时间": ("signed_at", "合同签订时间"),
            "完成时间": ("completed_at", "项目完成时间"),
            "用户/业主联系人及电话": ("client_contact", "客户联系人及电话"),
        }
        if case_table and normalized in case_attributes:
            attribute, display = case_attributes[normalized]
            return (
                f"business_case_{attribute}", f"business_case.{attribute}",
                EntityType.BUSINESS_CASE, attribute,
                f"BusinessCase.{attribute}", f"业绩案例{display}",
                SubjectRole.BUSINESS_CASE_LIBRARY,
                ("当前项目", "企业业绩库", "候选案例", display),
                FillStrategy.KNOWLEDGE_COLLECTION,
            )

        personnel_table = any(item in compact_context for item in (
            "经验年限", "承担工作内容", "担任职务", "学历", "职称",
        ))
        personnel_attributes = {
            "姓名": ("name", "姓名"),
            "性别": ("gender", "性别"),
            "年龄": ("age", "年龄"),
            "学历": ("education", "学历"),
            "职称": ("professional_title", "职称"),
            "专业": ("specialty", "专业"),
            "经验年限": ("experience_years", "经验年限"),
            "担任职务": ("title", "项目职务"),
            "承担工作内容": ("assignment", "承担工作内容"),
        }
        if personnel_table and normalized in personnel_attributes:
            attribute, display = personnel_attributes[normalized]
            return (
                f"person_{attribute}", f"person.{attribute}",
                EntityType.PERSON, attribute,
                f"Person[PROJECT_TEAM_ROW].{attribute}", f"项目团队人员{display}",
                SubjectRole.CURRENT_PROJECT,
                ("当前项目", "项目团队", "候选人员", display),
                FillStrategy.KNOWLEDGE_COLLECTION,
            )

        certificate_table = any(item in compact_context for item in (
            "证书名称", "发证单位", "证书等级", "证书有效期",
        ))
        certificate_attributes = {
            "证书名称": ("name", "证书名称"),
            "发证单位": ("issuer", "发证单位"),
            "证书等级": ("level", "证书等级"),
            "证书有效期": ("valid_until", "证书有效期"),
        }
        if certificate_table and normalized in certificate_attributes:
            attribute, display = certificate_attributes[normalized]
            return (
                f"certificate_{attribute}", f"certificate.{attribute}",
                EntityType.CERTIFICATE, attribute,
                f"Certificate.{attribute}", display,
                SubjectRole.CERTIFICATE_LIBRARY,
                ("当前项目", "企业证书库", "候选证书", display),
                FillStrategy.KNOWLEDGE_COLLECTION,
            )

        if normalized in {"服务期限", "履约期限", "项目工期", "工期"}:
            return (
                "project_service_term", "project.service_term",
                EntityType.PROJECT, "duration", "Project.service_term",
                "当前项目服务期限", SubjectRole.CURRENT_PROJECT,
                ("当前项目", "采购要求", "服务期限"),
                FillStrategy.DIRECT_ATTRIBUTE,
            )

        if re.search(r"(?:小写|大写|RMB)", normalized):
            return (
                "bid_price_amount", "bid_response.pricing.amount",
                None, "money", "BidResponseDocument.Pricing.amount",
                "本项目报价金额（大小写）", SubjectRole.BID_RESPONSE_DOCUMENT,
                ("当前项目", "投标文件", "报价表", "报价金额"),
                FillStrategy.KNOWLEDGE_COLLECTION,
            )
        return None

    @staticmethod
    def _generic_business_slot(
        label: str,
    ) -> tuple[
        str, str, EntityType | None, str, str, str,
        SubjectRole | None, tuple[str, ...],
    ] | None:
        """Bind common form columns to an object even before one row is chosen."""
        person_attributes = {
            "姓名": ("name", "姓名"),
            "性别": ("gender", "性别"),
            "年龄": ("age", "年龄"),
            "职务": ("title", "职务"),
            "职称": ("professional_title", "职称"),
            "技术职称": ("professional_title", "技术职称"),
            "常住地": ("residence", "常住地"),
            "证书名称": ("certificate_name", "证书名称"),
            "级别": ("certificate_level", "证书级别"),
            "证号": ("certificate_number", "证书编号"),
            "专业": ("specialty", "专业"),
            "学历": ("education", "学历"),
            "经验年限": ("experience_years", "经验年限"),
            "担任职务": ("title", "项目职务"),
            "承担工作内容": ("assignment", "承担工作内容"),
        }
        normalized = re.sub(r"\s+", "", label)
        if normalized in person_attributes:
            attribute, display = person_attributes[normalized]
            return (
                f"person_{attribute}", f"person.{attribute}",
                EntityType.PERSON, attribute,
                f"Person[UNBOUND_ROW].{attribute}", f"待绑定人员{display}",
                SubjectRole.CURRENT_PROJECT,
                ("当前项目", "人员清单", display),
            )
        organization_attributes = {
            "地址": ("registered_address", "注册地址"),
            "组织结构": ("organization_structure", "组织结构"),
            "成立时间": ("established_date", "成立时间"),
            "员工总人数": ("employee_count", "员工总人数"),
            "营业执照号": ("business_license_number", "营业执照编号"),
            "营业执照（注册号）": (
                "business_license_number", "营业执照注册号"
            ),
            "注册资金": ("registered_capital", "注册资金"),
            "开户银行": ("bank_name", "开户银行"),
            "经营范围": ("business_scope", "经营范围"),
            "经济性质": ("economic_nature", "经济性质"),
            "主营（产）": ("main_business", "主营业务"),
            "兼营（产）": ("secondary_business", "兼营业务"),
            "高级职称人员": ("senior_staff_count", "高级职称人员数量"),
            "中级职称人员": ("intermediate_staff_count", "中级职称人员数量"),
            "初级职称人员": ("junior_staff_count", "初级职称人员数量"),
            "技工": ("skilled_worker_count", "技工数量"),
        }
        if normalized in organization_attributes:
            attribute, display = organization_attributes[normalized]
            return (
                attribute, f"organization.{attribute}",
                EntityType.ORGANIZATION, attribute,
                f"Organization[BIDDER_ORGANIZATION].{attribute}",
                f"当前项目投标人{display}", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", display),
            )
        team_groups = {
            "管理人员": ("management_staff", "管理人员"),
            "技术人员": ("technical_staff", "技术人员"),
            "售后服务人员": ("after_sales_staff", "售后服务人员"),
        }
        if normalized in team_groups:
            key, display = team_groups[normalized]
            return (
                f"project_team_{key}", "project.team.members",
                EntityType.PERSON, "person_collection",
                f"ProjectTeam.{normalized}", f"项目团队{display}",
                SubjectRole.CURRENT_PROJECT,
                ("当前项目", "项目团队", display),
            )
        document_fields = {
            "资格性响应文件": ("qualification_response_materials", "资格响应材料"),
            "其他响应文件/电子档": ("other_response_materials", "其他响应材料"),
            "谈判采购文件要求": ("tender_requirement_text", "采购文件要求原文"),
            "响应文件的应答": ("response_content", "投标响应内容"),
            "响应文件的应答情况": ("response_status", "投标响应情况"),
            "项目内容": ("pricing_item_content", "报价项目内容"),
            "不含税总价（元）": ("total_price_excluding_tax", "不含税报价总额"),
            "含税总价（元）": ("total_price_including_tax", "含税报价总额"),
            "备注": ("notes", "备注"),
            "偏离说明": ("deviation_notes", "偏离说明"),
        }
        if normalized in document_fields:
            key, display = document_fields[normalized]
            return (
                key,
                "bid_response.content", None, "response_content",
                "BidResponseDocument.content", display,
                SubjectRole.BID_RESPONSE_DOCUMENT,
                ("当前项目", "投标文件", display),
            )
        return None

    @staticmethod
    def _aggregate_staffing_slot(
        label: str,
        surrounding_text: str,
    ) -> tuple[
        str, str, EntityType, str, str, str,
        SubjectRole, tuple[str, ...],
    ] | None:
        """Recognize staffing totals without turning a role name into a person."""
        normalized = re.sub(r"\s+", "", label)
        context = re.sub(r"\s+", "", surrounding_text)
        if (
            normalized in {"项目经理", "项目负责人"}
            and "其中" in context
            and re.search(r"员工总人数|职称人员|技工", context)
        ):
            return (
                "project_manager_count",
                "organization.project_manager_count",
                EntityType.ORGANIZATION,
                "count",
                "Organization[BIDDER_ORGANIZATION].project_manager_count",
                "当前项目投标人项目经理人数",
                SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "项目经理人数"),
            )
        return None

    @staticmethod
    def _build_slot(
        *, label: str, surrounding_text: str, source_location: str,
        document_section: str | None, table_index: int | None,
        paragraph_index: int | None, row: int | None, column: int | None,
        semantic_field: str, canonical_key: str,
        entity_type: EntityType | None, role: ProjectRole | None,
        value_type: str, confidence: float, ontology_concept: str,
        display_name: str, subject_role: SubjectRole | None,
        relation_path: tuple[str, ...], value_expression: str | None,
        fill_strategy: FillStrategy,
        required_actions: tuple[str, ...],
    ) -> DocumentSlot:
        slot_id = hashlib.sha256(
            f"{source_location}|{label}|{surrounding_text}".encode()
        ).hexdigest()[:20]
        clean_context = re.sub(r"\s+", " ", surrounding_text).strip()
        return DocumentSlot(
            slot_id=slot_id,
            document_section=document_section,
            table_index=table_index,
            paragraph_index=paragraph_index,
            row=row,
            column=column,
            surrounding_text=clean_context,
            source_location=source_location,
            semantic_field=semantic_field,
            canonical_key=canonical_key,
            expected_entity_type=entity_type,
            expected_role=role,
            expected_value_type=value_type,
            source_requirement=clean_context or None,
            confidence=confidence,
            ontology_concept=ontology_concept,
            display_name=display_name,
            subject_role=subject_role,
            relation_path=relation_path,
            value_expression=value_expression,
            fill_strategy=fill_strategy,
            required_actions=required_actions,
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

    @classmethod
    def _nearest_role(
        cls,
        context: str,
        marker_index: int,
    ) -> ProjectRole | None:
        if marker_index < 0:
            return None
        distances: list[tuple[int, ProjectRole]] = []
        for role, aliases in cls._configured_role_aliases():
            positions = [
                match.start()
                for alias in aliases
                for match in re.finditer(re.escape(alias), context)
            ]
            if positions:
                distances.append((min(abs(item - marker_index) for item in positions), role))
        if not distances:
            return None
        distances.sort(key=lambda item: item[0])
        if len(distances) > 1 and distances[0][0] == distances[1][0]:
            return None
        return distances[0][1]

    @classmethod
    def _required_actions(
        cls,
        text: str,
        *,
        role: ProjectRole | None = None,
    ) -> tuple[str, ...]:
        normalized = re.sub(r"\s+", "", text)
        if (
            re.search(r"签字|签名|签署", normalized)
            and re.search(r"法定代表人|法人代表|法人", normalized)
            and re.search(r"委托代理人|授权代表|授权代理人", normalized)
        ):
            return ("法定代表人或授权代表签字",)
        labels: list[str] = []
        for details in cls._ontology().get("document_actions", {}).values():
            if any(
                str(alias) in normalized
                for alias in details.get("aliases", ())
            ):
                labels.append(str(details.get("label") or "文档动作"))
        if any(label in labels for label in ("甲方签章", "乙方签章")):
            labels = [
                label for label in labels
                if label != "加盖投标人公章"
            ]
        if role is not None and "由对应人员签字" in labels:
            labels = [
                f"{ROLE_LABELS[role]}签字"
                if label == "由对应人员签字" else label
                for label in labels
            ]
        return tuple(dict.fromkeys(labels))

    @staticmethod
    def _is_action_only(label: str) -> bool:
        compact = re.sub(r"[：:()（）_＿\s]", "", label)
        if not re.search(r"公章|盖章|签章|签字|签名|签署", compact):
            return False
        remainder = re.sub(
            r"甲方|乙方|采购人|招标人|投标人|供应商|响应人|单位|企业|"
            r"法定代表人|委托代理人|授权代表|代理人|负责人|对应人员|本人",
            "",
            compact,
        )
        remainder = re.sub(
            r"加盖|盖公章|公章|盖章|签章|亲笔签署|签署|签字|签名|"
            r"或|和|及|、|由|其",
            "",
            remainder,
        )
        return not remainder

    @staticmethod
    def _attribute_label(semantic_field: str) -> str:
        return {
            "person.name": "姓名",
            "person.id_number": "身份证号码",
            "person.title": "职务",
            "person.professional_title": "技术职称",
            "person.phone": "联系电话",
            "organization.full_name": "企业全称",
            "organization.registered_address": "注册地址",
        }.get(semantic_field, "属性值")

    @staticmethod
    def _organization_subject_role(context: str) -> SubjectRole:
        if "联合体牵头人" in context or "联合体主办方" in context:
            return SubjectRole.CONSORTIUM_LEAD
        if "联合体成员" in context:
            return SubjectRole.CONSORTIUM_MEMBER
        return SubjectRole.BIDDER_ORGANIZATION

    @staticmethod
    def _subject_role_label(role: SubjectRole) -> str:
        return {
            SubjectRole.BIDDER_ORGANIZATION: "投标人",
            SubjectRole.CONSORTIUM_LEAD: "联合体牵头人",
            SubjectRole.CONSORTIUM_MEMBER: "联合体成员",
            SubjectRole.CURRENT_PROJECT: "当前项目",
            SubjectRole.BID_RESPONSE_DOCUMENT: "本项目投标文件",
            SubjectRole.DOCUMENT_ACTION: "文档动作",
            SubjectRole.BUSINESS_CASE_LIBRARY: "企业业绩库",
            SubjectRole.CERTIFICATE_LIBRARY: "企业证书库",
            SubjectRole.RESPONSE_TABLE: "响应表",
            SubjectRole.DOCUMENT_LAYOUT: "原模板格式",
        }[role]

    @staticmethod
    def _non_person_ontology(
        canonical_key: str,
    ) -> tuple[
        str, str, SubjectRole | None, tuple[str, ...], str | None,
        FillStrategy,
    ]:
        mappings = {
            "project_name": (
                "Project.name", "当前项目名称", SubjectRole.CURRENT_PROJECT,
                ("当前项目", "项目名称"), "current_project.name",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "project_number": (
                "Project.number", "当前项目编号", SubjectRole.CURRENT_PROJECT,
                ("当前项目", "项目编号"), "current_project.number",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "project_reference": (
                "Project.reference", "当前项目名称及编号",
                SubjectRole.CURRENT_PROJECT,
                ("当前项目", "组合项目名称与项目编号"),
                "compose(current_project.name,current_project.number)",
                FillStrategy.COMPOSED_VALUE,
            ),
            "bid_response_signing_date": (
                "BidResponseDocument.signing_date", "本项目投标文件签署日期",
                SubjectRole.BID_RESPONSE_DOCUMENT,
                ("当前项目", "投标文件", "签署日期"),
                "current_project.bid_response.signing_date",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "registered_address": (
                "Organization[BIDDER_ORGANIZATION].registered_address",
                "当前项目投标人注册地址", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "注册地址"),
                "current_project.bidder.registered_address",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "postal_code": (
                "Organization[BIDDER_ORGANIZATION].postal_code",
                "当前项目投标人邮政编码", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "邮政编码"),
                "current_project.bidder.postal_code",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "bank_account": (
                "Organization[BIDDER_ORGANIZATION].bank_account",
                "当前项目投标人银行账号", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "银行账号"),
                "current_project.bidder.bank_account",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "fax": (
                "Organization[BIDDER_ORGANIZATION].fax",
                "当前项目投标人传真", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "传真"),
                "current_project.bidder.fax",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "website": (
                "Organization[BIDDER_ORGANIZATION].website",
                "当前项目投标人网址", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "网址"),
                "current_project.bidder.website",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "enterprise_qualification": (
                "Organization[BIDDER_ORGANIZATION].qualification",
                "当前项目投标人企业资质", SubjectRole.BIDDER_ORGANIZATION,
                ("当前项目", "投标人", "企业资质"),
                "current_project.bidder.qualification",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
            "bid_round": (
                "BidResponseDocument.bid_round", "本次报价轮次",
                SubjectRole.BID_RESPONSE_DOCUMENT,
                ("当前项目", "投标文件", "报价轮次"),
                "current_project.bid_response.bid_round",
                FillStrategy.DIRECT_ATTRIBUTE,
            ),
        }
        return mappings.get(
            canonical_key,
            (
                "UnmappedSlot", "尚未识别的业务槽位", None,
                ("当前文档", "待解析业务关系"), None,
                FillStrategy.UNRESOLVED,
            ),
        )

    @staticmethod
    def _non_person_field(
        label: str,
        context: str,
        canonical_hint: str | None,
    ) -> tuple[str | None, str, EntityType | None, str]:
        if (
            re.search(r"项目名称|采购项目名称|招标项目名称", label)
            and re.search(r"项目编号|采购编号|招标编号|包号", label)
            and not re.search(r"[_＿]{2,}|…+|\.{3,}", label)
        ):
            return (
                "project_reference", "project.reference",
                EntityType.PROJECT, "project_reference",
            )
        semantic_by_key = {
            "bidder_name": ("organization.full_name", EntityType.ORGANIZATION),
            "registered_address": ("organization.registered_address", EntityType.ORGANIZATION),
            "postal_code": ("organization.postal_code", EntityType.ORGANIZATION),
            "project_name": ("project.project_name", EntityType.PROJECT),
            "project_number": ("project.project_number", EntityType.PROJECT),
            "project_reference": ("project.reference", EntityType.PROJECT),
            "contact_person": ("person.name", EntityType.PERSON),
            "contact_phone": ("person.phone", EntityType.PERSON),
            "date": ("bid_response.signing_date", None),
            "bid_response_signing_date": ("bid_response.signing_date", None),
            "bank_account": ("organization.bank_account", EntityType.ORGANIZATION),
            "enterprise_qualification": ("organization.qualification", EntityType.ORGANIZATION),
            "fax": ("organization.fax", EntityType.ORGANIZATION),
            "website": ("organization.website", EntityType.ORGANIZATION),
            "bid_round": ("bid_response.bid_round", None),
        }
        if canonical_hint in semantic_by_key:
            semantic, entity_type = semantic_by_key[canonical_hint]
            from app.core.field_semantics import FieldSemanticClassifier

            normalized_key = (
                "bid_response_signing_date"
                if canonical_hint == "date" else canonical_hint
            )
            return (
                normalized_key,
                semantic,
                entity_type,
                FieldSemanticClassifier.expected_type(canonical_hint).value,
            )
        mappings = (
            ("project_number", "project.project_number", EntityType.PROJECT, "project_identifier", ("项目编号", "采购编号", "招标编号")),
            ("project_name", "project.project_name", EntityType.PROJECT, "project_name", ("项目名称", "采购项目名称", "招标项目名称")),
            ("registered_address", "organization.registered_address", EntityType.ORGANIZATION, "address", ("注册地址", "地址")),
            ("contact_phone", "person.phone", EntityType.PERSON, "phone", ("联系电话", "手机", "电话")),
            ("postal_code", "organization.postal_code", EntityType.ORGANIZATION, "postal_code", ("邮政编码", "邮编")),
            ("bank_account", "organization.bank_account", EntityType.ORGANIZATION, "bank_account", ("银行账号", "账号")),
            ("enterprise_qualification", "organization.qualification", EntityType.ORGANIZATION, "qualification", ("企业资质", "资质等级")),
            ("fax", "organization.fax", EntityType.ORGANIZATION, "phone", ("传真",)),
            ("website", "organization.website", EntityType.ORGANIZATION, "website", ("网址", "网站")),
            ("bid_round", "bid_response.bid_round", None, "bid_round", ("报价轮次", "轮次")),
            ("bid_response_signing_date", "bid_response.signing_date", None, "date", ("日期", "年月日")),
        )
        for key, semantic, entity_type, value_type, aliases in mappings:
            if any(alias in label for alias in aliases):
                return key, semantic, entity_type, value_type
        if canonical_hint:
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


class SlotSemanticContractValidator:
    """Validate slot meaning before an entity graph is allowed to resolve it.

    Classification answers what the blank means; entity resolution later
    answers which verified object supplies the value.  Keeping this contract
    rule-driven prevents a graph or vector search from compensating for a
    wrongly typed slot.
    """

    @classmethod
    def audit(cls, fields: list[dict[str, Any]]) -> dict[str, Any]:
        ontology = SlotContextClassifier._ontology()
        contracts = tuple(ontology.get("semantic_contracts") or ())
        validation = ontology.get("semantic_validation") or {}
        unknown_fields = set(validation.get("unknown_fields") or ())
        unknown_value_types = set(
            validation.get("unknown_value_types") or ()
        )
        generic_names = set(validation.get("generic_display_names") or ())
        issues: list[dict[str, str]] = []

        for raw in fields:
            slot = DocumentSlot.from_snapshot(raw)
            actual_entity = (
                slot.expected_entity_type.value
                if slot.expected_entity_type else None
            )
            contract = next(
                (
                    item for item in contracts
                    if slot.semantic_field.startswith(
                        str(item.get("prefix") or "")
                    )
                ),
                None,
            )
            if contract is None or slot.semantic_field in unknown_fields:
                cls._issue(
                    issues, slot, "semantic_field_unregistered",
                    "空位尚未映射到已登记的业务属性。",
                )
            elif actual_entity != contract.get("entity_type"):
                cls._issue(
                    issues, slot, "entity_type_mismatch",
                    "业务属性与目标实体类型不一致。",
                )
            if slot.expected_value_type in unknown_value_types:
                cls._issue(
                    issues, slot, "value_type_unknown",
                    "空位没有明确的值类型。",
                )
            if (
                not slot.ontology_concept
                or slot.ontology_concept == "unmapped"
                or not slot.relation_path
            ):
                cls._issue(
                    issues, slot, "relation_path_missing",
                    "空位尚未建立从当前项目到目标属性的关系路径。",
                )
            if slot.display_name in generic_names:
                cls._issue(
                    issues, slot, "display_name_generic",
                    "空位仍使用泛化名称，无法向业务人员说明实际含义。",
                )
            if (
                slot.expected_entity_type is EntityType.PERSON
                and slot.expected_role is None
                and slot.table_index is None
                and slot.expected_value_type != "person_collection"
            ):
                cls._issue(
                    issues, slot, "person_role_missing",
                    "非人员清单中的人员字段必须先绑定项目角色。",
                )
            if slot.table_index is not None and (
                slot.row is None or slot.column is None
            ):
                cls._issue(
                    issues, slot, "table_coordinate_missing",
                    "表格空位缺少行列坐标。",
                )
            if slot.table_index is None and slot.paragraph_index is None:
                cls._issue(
                    issues, slot, "document_coordinate_missing",
                    "空位缺少表格或段落定位信息。",
                )

        invalid_slots = {
            (item["source_location"], item["display_name"])
            for item in issues
        }
        return {
            "version": str(ontology.get("version") or "unknown"),
            "status": "passed" if not issues else "review_required",
            "field_count": len(fields),
            "valid_field_count": len(fields) - len(invalid_slots),
            "issue_count": len(issues),
            "issues": issues,
        }

    @staticmethod
    def _issue(
        issues: list[dict[str, str]],
        slot: DocumentSlot,
        code: str,
        message: str,
    ) -> None:
        issues.append({
            "source_location": slot.source_location,
            "display_name": slot.display_name,
            "code": code,
            "message": message,
        })


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
            if slot.subject_role in {
                SubjectRole.CONSORTIUM_LEAD,
                SubjectRole.CONSORTIUM_MEMBER,
            }:
                role_label = SlotContextClassifier._subject_role_label(
                    slot.subject_role
                )
                return SlotResolution(
                    "binding_required", None, None, (),
                    f"当前项目尚未绑定{role_label}，不能使用投标人名称代替。",
                    (
                        f"槽位主体：{role_label}",
                        "检查当前项目联合体组织关系",
                        "未获得唯一组织实体",
                    ),
                )
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
