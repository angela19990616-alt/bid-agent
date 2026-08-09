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


class SubjectRole(StrEnum):
    CURRENT_PROJECT = "CURRENT_PROJECT"
    BIDDER_ORGANIZATION = "BIDDER_ORGANIZATION"
    CONSORTIUM_LEAD = "CONSORTIUM_LEAD"
    CONSORTIUM_MEMBER = "CONSORTIUM_MEMBER"
    BID_RESPONSE_DOCUMENT = "BID_RESPONSE_DOCUMENT"
    DOCUMENT_ACTION = "DOCUMENT_ACTION"


class FillStrategy(StrEnum):
    DIRECT_ATTRIBUTE = "direct_attribute"
    COMPOSED_VALUE = "composed_value"
    ACTION_ONLY = "action_only"
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
        # Resolve the relationship nearest to the blank.  An authorization
        # sentence commonly mentions both the legal representative and the
        # agent; the verb phrase around the blank is authoritative.
        if person_value_slot and re.search(
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
        compact_label = re.sub(r"\s+", "", label)
        required_actions = cls._required_actions(
            f"{compact_label}{surrounding_text}"
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
        organization_field = bool(
            re.search(r"投标人|供应商|响应人|单位|企业|联合体", compact_label)
            and re.search(r"名称|全称", compact_label)
        )
        if organization_field:
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
    def _required_actions(cls, text: str) -> tuple[str, ...]:
        normalized = re.sub(r"\s+", "", text)
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
            r"或|和|及|、|由",
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
        combined = f"{label}{context}"
        if (
            re.search(r"项目名称|采购项目名称|招标项目名称", label)
            and re.search(r"项目编号|采购编号|招标编号|包号", label)
            and not re.search(r"[_＿]{2,}|…+|\.{3,}", label)
        ):
            return (
                "project_reference", "project.reference",
                EntityType.PROJECT, "project_reference",
            )
        mappings = (
            ("project_number", "project.project_number", EntityType.PROJECT, "project_identifier", ("项目编号", "采购编号", "招标编号")),
            ("project_name", "project.project_name", EntityType.PROJECT, "project_name", ("项目名称", "采购项目名称", "招标项目名称")),
            ("registered_address", "organization.registered_address", EntityType.ORGANIZATION, "address", ("注册地址", "地址")),
            ("contact_phone", "person.phone", EntityType.PERSON, "phone", ("联系电话", "手机", "电话")),
            ("postal_code", "organization.postal_code", EntityType.ORGANIZATION, "postal_code", ("邮政编码", "邮编")),
            ("bank_account", "organization.bank_account", EntityType.ORGANIZATION, "bank_account", ("银行账号", "账号")),
            ("enterprise_qualification", "organization.qualification", EntityType.ORGANIZATION, "qualification", ("企业资质", "资质等级")),
            ("bid_round", "bid_response.bid_round", None, "bid_round", ("报价轮次", "轮次")),
            ("bid_response_signing_date", "bid_response.signing_date", None, "date", ("日期", "年月日")),
        )
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
                "project_reference": ("project.reference", EntityType.PROJECT),
                "contact_person": ("person.name", EntityType.PERSON),
                "contact_phone": ("person.phone", EntityType.PERSON),
                "date": ("bid_response.signing_date", None),
                "bid_response_signing_date": ("bid_response.signing_date", None),
                "bank_account": ("organization.bank_account", EntityType.ORGANIZATION),
                "enterprise_qualification": ("organization.qualification", EntityType.ORGANIZATION),
                "bid_round": ("bid_response.bid_round", None),
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
