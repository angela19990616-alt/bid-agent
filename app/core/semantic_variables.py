from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.entity_resolution import DocumentSlot, FillStrategy, SubjectRole


@dataclass(frozen=True)
class VariableDefinition:
    variable_key: str
    standard_name: str
    aliases: tuple[str, ...]
    semantic_field: str
    target_entity_type: str | None
    target_relation: str | None
    expected_value_type: str
    source_priority: tuple[str, ...]
    entity_scope_label: str


class VariableDictionary:
    """Map document slots to stable business variables.

    A variable identifies one business fact.  It deliberately contains no
    project value: values are resolved from the current entity graph each time.
    """

    @staticmethod
    @lru_cache(maxsize=1)
    def _content() -> dict[str, Any]:
        path = (
            Path(__file__).resolve().parents[2]
            / "config" / "rules" / "variable_dictionary.default.json"
        )
        return json.loads(path.read_text(encoding="utf-8"))

    @classmethod
    def version(cls) -> str:
        return str(cls._content().get("version") or "unknown")

    @classmethod
    def resolve(
        cls,
        slot: DocumentSlot,
        *,
        resolved_entity_type: str | None = None,
        resolved_entity_id: str | None = None,
    ) -> VariableDefinition:
        content = cls._content()
        priorities = tuple(content.get("source_priority") or ())
        configured = cls._configured_definition(content, slot, priorities)
        if configured is not None:
            return configured
        if resolved_entity_type and resolved_entity_id:
            entity_token = hashlib.sha256(
                f"{resolved_entity_type}:{resolved_entity_id}".encode("utf-8")
            ).hexdigest()[:16]
            attribute = slot.semantic_field.rsplit(".", 1)[-1]
            return VariableDefinition(
                variable_key=(
                    f"entity_fact.{resolved_entity_type.lower()}."
                    f"{entity_token}.{attribute}"
                ),
                standard_name=slot.display_name or "已绑定实体属性",
                aliases=(slot.canonical_key, slot.display_name),
                semantic_field=slot.semantic_field,
                target_entity_type=resolved_entity_type,
                target_relation=(
                    slot.expected_role.value if slot.expected_role else None
                ),
                expected_value_type=slot.expected_value_type,
                source_priority=priorities,
                entity_scope_label=(
                    "已绑定人员"
                    if resolved_entity_type == "Person"
                    else "当前投标人"
                    if resolved_entity_type == "Organization"
                    else "当前项目"
                ),
            )
        if slot.expected_role is not None and slot.semantic_field.startswith(
            "person."
        ):
            role = content.get("person_role_scopes", {}).get(
                slot.expected_role.value
            )
            attribute = content.get("person_attributes", {}).get(
                slot.semantic_field
            )
            if role and attribute:
                return VariableDefinition(
                    variable_key=f"{role['path']}.{attribute['suffix']}",
                    standard_name=(
                        f"{role['standard_name']}{attribute['label']}"
                    ),
                    aliases=(slot.canonical_key, slot.display_name),
                    semantic_field=slot.semantic_field,
                    target_entity_type="Person",
                    target_relation=slot.expected_role.value,
                    expected_value_type=str(
                        attribute.get("expected_value_type")
                        or slot.expected_value_type
                    ),
                    source_priority=priorities,
                    entity_scope_label=str(role["standard_name"]),
                )

        # Collection rows represent different business objects even when they
        # share a column label.  Never merge five cases, people, certificates
        # or response rows into one value merely because each column says the
        # same thing.
        if (
            slot.semantic_field.startswith("person.")
            or (
                slot.expected_entity_type is not None
                and slot.expected_entity_type.value in {
                    "BusinessCase", "Certificate", "ResponseItem",
                }
            )
            or slot.fill_strategy in {
                FillStrategy.GENERATED_COLLECTION,
                FillStrategy.KNOWLEDGE_COLLECTION,
            }
        ):
            return cls._fallback(slot, priorities, unique=True)
        return cls._fallback(slot, priorities, unique=False)

    @classmethod
    def _configured_definition(
        cls,
        content: dict[str, Any],
        slot: DocumentSlot,
        priorities: tuple[str, ...],
    ) -> VariableDefinition | None:
        """Resolve stable project facts before entity-resolution enrichment.

        An entity id proves where a value came from; it must not change the
        identity of a configured business variable.  Subject-role matching
        keeps consortium and counterparty organizations separate from the
        current bidder.
        """
        for item in content.get("variables", ()):
            aliases = {str(value) for value in item.get("aliases", ())}
            if not (
                item.get("semantic_field") == slot.semantic_field
                or slot.canonical_key in aliases
            ):
                continue
            target_relation = str(item.get("target_relation") or "")
            if (
                slot.subject_role is not None
                and target_relation in {role.value for role in SubjectRole}
                and target_relation != slot.subject_role.value
            ):
                continue
            return VariableDefinition(
                variable_key=str(item["variable_key"]),
                standard_name=str(item["standard_name"]),
                aliases=tuple(str(value) for value in aliases),
                semantic_field=str(item["semantic_field"]),
                target_entity_type=item.get("target_entity_type"),
                target_relation=item.get("target_relation"),
                expected_value_type=str(
                    item.get("expected_value_type")
                    or slot.expected_value_type
                ),
                source_priority=priorities,
                entity_scope_label=str(
                    item.get("entity_scope_label")
                    or cls._scope_label(item.get("target_relation"))
                ),
            )
        return None

    @staticmethod
    def _fallback(
        slot: DocumentSlot,
        priorities: tuple[str, ...],
        *,
        unique: bool,
    ) -> VariableDefinition:
        label = re.sub(r"\s+", "", slot.display_name or slot.canonical_key)
        signature = "|".join((
            slot.semantic_field,
            slot.subject_role.value if slot.subject_role else "",
            slot.expected_role.value if slot.expected_role else "",
            slot.canonical_key,
            label,
            slot.slot_id if unique else "",
        ))
        digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
        return VariableDefinition(
            variable_key=f"unresolved.{digest}",
            standard_name=slot.display_name or "待确认业务变量",
            aliases=(slot.canonical_key, slot.display_name),
            semantic_field=slot.semantic_field,
            target_entity_type=(
                slot.expected_entity_type.value
                if slot.expected_entity_type else None
            ),
            target_relation=(
                slot.expected_role.value if slot.expected_role else None
            ),
            expected_value_type=slot.expected_value_type,
            source_priority=priorities,
            entity_scope_label=VariableDictionary._fallback_scope_label(slot),
        )

    @staticmethod
    def _scope_label(relation: Any) -> str:
        return {
            "CURRENT_PROJECT": "当前项目",
            "BIDDER_ORGANIZATION": "当前投标人",
            "BID_RESPONSE_DOCUMENT": "本次投标文件",
        }.get(str(relation or ""), "待确认业务对象")

    @staticmethod
    def _fallback_scope_label(slot: DocumentSlot) -> str:
        if (
            slot.expected_entity_type
            and slot.expected_entity_type.value == "Person"
        ):
            if slot.table_index is not None and slot.row is not None:
                return f"人员表第 {slot.row + 1} 行候选人员"
            return "待绑定人员"
        if slot.expected_entity_type:
            collection_labels = {
                "BusinessCase": "企业业绩候选",
                "Certificate": "企业证书候选",
                "ResponseItem": "招标响应事项",
            }
            if slot.expected_entity_type.value in collection_labels:
                return collection_labels[slot.expected_entity_type.value]
            return f"待绑定{slot.expected_entity_type.value}"
        if slot.fill_strategy is FillStrategy.AUTO_LAYOUT:
            return "原模板格式"
        return "本次投标文件"


class SlotDeduplicationEngine:
    """Collapse many physical fields into auditable business variables."""

    STATUS_RANK = {"AUTO_FILL": 0, "REVIEW_REQUIRED": 1, "MISSING": 2}

    @classmethod
    def group_decisions(
        cls, field_decisions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[VariableDefinition, dict[str, Any]]]] = {}
        order: list[str] = []
        for decision in field_decisions:
            slot = DocumentSlot.from_snapshot(decision.get("slot") or {
                "slot_id": decision.get("field_key"),
                "canonical_key": decision.get("canonical_key"),
                "semantic_field": decision.get("semantic_field") or "text.value",
                "expected_entity_type": decision.get("expected_entity_type"),
                "expected_role": decision.get("expected_role"),
                "expected_value_type": decision.get("expected_value_type"),
                "display_name": decision.get("display_name") or decision.get("label"),
                "surrounding_text": decision.get("label"),
                "fill_strategy": decision.get("fill_strategy") or FillStrategy.UNRESOLVED.value,
            })
            definition = VariableDictionary.resolve(
                slot,
                resolved_entity_type=decision.get("resolved_entity_type"),
                resolved_entity_id=decision.get("resolved_entity_id"),
            )
            if definition.variable_key not in grouped:
                grouped[definition.variable_key] = []
                order.append(definition.variable_key)
            grouped[definition.variable_key].append((definition, decision))
        return [cls._merge(grouped[key]) for key in order]

    @classmethod
    def _merge(
        cls,
        items: list[tuple[VariableDefinition, dict[str, Any]]],
    ) -> dict[str, Any]:
        definition = items[0][0]
        decisions = [item[1] for item in items]
        values = {
            str(item.get("value")).strip()
            for item in decisions if item.get("value")
        }
        if len(values) > 1:
            value = None
            status = "REVIEW_REQUIRED"
            reason = "同一业务变量出现多个不同值，需要先核验企业事实口径。"
        else:
            value = next(iter(values), None)
            worst = max(
                decisions,
                key=lambda item: cls.STATUS_RANK.get(item.get("status"), 2),
            )
            status = str(worst.get("status") or "MISSING")
            reason = str(worst.get("reason") or "尚未解析该业务变量。")
            if value and status == "MISSING":
                status = "REVIEW_REQUIRED"
                reason = "部分文档位置缺少一致证据，需要一次性核验该业务变量。"
        primary = next(
            (item for item in decisions if item.get("value") == value),
            decisions[0],
        )
        aliases = list(dict.fromkeys(
            str(item.get("display_name") or item.get("label") or "").strip()
            for item in decisions
            if item.get("display_name") or item.get("label")
        ))
        slots = [cls._slot_snapshot(item) for item in decisions]
        value_candidates = cls._value_candidates(decisions)
        entity_candidates = cls._entity_candidates(decisions)
        target_relations = list(dict.fromkeys(
            item[0].target_relation
            for item in items if item[0].target_relation
        ))
        semantic_review_required = any(
            bool((item.get("semantic_resolution") or {}).get(
                "requires_human_review"
            ))
            for item in decisions
        )
        if semantic_review_required:
            status = "REVIEW_REQUIRED"
            reason = (
                "系统结合原文上下文后仍无法唯一判断该业务变量，"
                "需人工确认字段含义后再回填。"
            )
        standard_name = definition.standard_name
        if definition.target_entity_type == "Person" and len(target_relations) > 1:
            standard_name = f"同一已绑定人员{primary.get('expected_value_type_label', '属性')}"
        resolution = cls._resolution(
            definition=definition,
            primary=primary,
            status=status,
            value=value,
            standard_name=standard_name,
            semantic_review_required=semantic_review_required,
        )
        review_group_key, review_group_label = cls._review_group(
            definition=definition,
            primary=primary,
            slots=slots,
        )
        return {
            "variable_key": definition.variable_key,
            "dictionary_version": VariableDictionary.version(),
            "standard_name": standard_name,
            "label": standard_name,
            "aliases": aliases,
            "semantic_field": definition.semantic_field,
            "target_entity_type": definition.target_entity_type,
            "target_relation": definition.target_relation,
            "target_relations": target_relations,
            "entity_scope_label": definition.entity_scope_label,
            "expected_value_type": definition.expected_value_type,
            "expected_value_type_label": primary.get(
                "expected_value_type_label", "文本"
            ),
            "source_priority": list(definition.source_priority),
            "value": value,
            "status": status,
            "reason": reason,
            "confidence": min(
                (float(item.get("confidence") or 0) for item in decisions),
                default=0,
            ),
            "required": any(bool(item.get("required", True)) for item in decisions),
            "slot_count": len(slots),
            "affected_locations": list(dict.fromkeys(
                slot["source_location"] for slot in slots
            )),
            "slots": slots,
            "source_type": primary.get("source_type"),
            "source_reference": primary.get("source_reference"),
            "evidence_title": primary.get("evidence_title"),
            "evidence_excerpt": primary.get("evidence_excerpt"),
            "evidence_location": primary.get("evidence_location"),
            "evidence_match_count": primary.get("evidence_match_count", 0),
            "evidence_alternatives": primary.get("evidence_alternatives") or [],
            "value_candidates": value_candidates,
            "binding_status": primary.get("binding_status"),
            "relation_path": primary.get("relation_path") or [],
            "entity_candidates": entity_candidates,
            "fill_strategy": primary.get("fill_strategy") or "unresolved",
            "personnel_rule_results": primary.get("personnel_rule_results") or [],
            **resolution,
            "review_group_key": review_group_key,
            "review_group_label": review_group_label,
            "_field_decisions": decisions,
        }

    @staticmethod
    def _value_candidates(
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            for candidate in decision.get("value_candidates") or ():
                key = str(candidate.get("value") or "").strip()
                if key and key not in by_key:
                    by_key[key] = dict(candidate)
        return list(by_key.values())

    @staticmethod
    def _entity_candidates(
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_key: dict[str, dict[str, Any]] = {}
        for decision in decisions:
            for candidate in decision.get("entity_candidates") or ():
                key = str(
                    candidate.get("organization_id")
                    or candidate.get("person_id")
                    or ""
                ).strip()
                if key and key not in by_key:
                    by_key[key] = dict(candidate)
        return list(by_key.values())

    @staticmethod
    def _resolution(
        *,
        definition: VariableDefinition,
        primary: dict[str, Any],
        status: str,
        value: str | None,
        standard_name: str,
        semantic_review_required: bool = False,
    ) -> dict[str, Any]:
        """Explain whether semantics or only the target value is unresolved.

        ``fill_strategy=unresolved`` is an execution strategy, not proof that
        the business meaning is unknown.  Keep that internal distinction out
        of the review UI.
        """
        semantic_field = (definition.semantic_field or "").strip()
        semantics_recognized = bool(
            semantic_field
            and semantic_field not in {"text.value", "unknown", "unmapped"}
            and standard_name not in {
                "尚未识别的业务槽位",
                "待确认业务变量",
                "待识别字段",
            }
        )
        if semantic_review_required:
            return {
                "semantics_recognized": False,
                "resolution_state": "semantic_review_required",
                "resolution_label": "需要确认字段含义",
                "next_action": (
                    "系统无法从原文上下文唯一判断该空位含义，"
                    "请确认一次，所有同类位置将同步更新。"
                ),
            }
        if value and status == "AUTO_FILL":
            return {
                "semantics_recognized": semantics_recognized,
                "resolution_state": "resolved",
                "resolution_label": "已自动匹配",
                "next_action": "请核验来源；确认无误后可直接导出。",
            }
        if value and status == "REVIEW_REQUIRED":
            return {
                "semantics_recognized": semantics_recognized,
                "resolution_state": "review_required",
                "resolution_label": "待人工核验",
                "next_action": "已找到候选值，请核验来源和取值后确认。",
            }
        fill_strategy = str(primary.get("fill_strategy") or "")
        if fill_strategy == FillStrategy.AUTO_LAYOUT.value:
            return {
                "semantics_recognized": True,
                "resolution_state": "layout_managed",
                "resolution_label": "系统按原模板自动处理",
                "next_action": "序号、页码和版式由系统统一编排，不需要逐格审核。",
            }
        if fill_strategy == FillStrategy.GENERATED_COLLECTION.value:
            return {
                "semantics_recognized": True,
                "resolution_state": "response_generation_pending",
                "resolution_label": "待按整表生成响应",
                "next_action": "系统将依据采购要求生成整张响应表，业务人员只审核整表结果。",
            }
        if not semantics_recognized:
            return {
                "semantics_recognized": False,
                "resolution_state": "semantic_review_required",
                "resolution_label": "需要确认字段含义",
                "next_action": "系统无法从上下文唯一判断该空位含义，请人工确认。",
            }
        if semantic_field == "bid_response.content":
            return {
                "semantics_recognized": True,
                "resolution_state": "response_generation_pending",
                "resolution_label": "待生成响应内容",
                "next_action": "系统将依据对应招标要求和已核验资料生成响应内容。",
            }
        if definition.target_entity_type == "Person":
            if primary.get("binding_status") == "resolved":
                state = "person_fact_pending"
                label = "人员资料待补齐"
                action = "人员已确定，系统将从该人员的受控档案继续匹配此项资料。"
            else:
                state = "person_binding_pending"
                label = "待选择项目人员"
                action = "请从已核验人员候选中确认本项目角色，其他字段将自动联动。"
            return {
                "semantics_recognized": True,
                "resolution_state": state,
                "resolution_label": label,
                "next_action": action,
            }
        if definition.target_entity_type in {"BusinessCase", "Certificate"}:
            label = (
                "业绩案例"
                if definition.target_entity_type == "BusinessCase"
                else "企业证书"
            )
            return {
                "semantics_recognized": True,
                "resolution_state": "knowledge_match_pending",
                "resolution_label": f"待匹配{label}",
                "next_action": f"系统将从已核验企业资料中匹配{label}并按整表回填。",
            }
        if definition.target_entity_type == "Organization":
            return {
                "semantics_recognized": True,
                "resolution_state": "enterprise_fact_pending",
                "resolution_label": "待匹配企业资料",
                "next_action": "系统将从当前投标人的已核验企业资料中继续匹配。",
            }
        if definition.target_entity_type == "Project":
            return {
                "semantics_recognized": True,
                "resolution_state": "project_fact_pending",
                "resolution_label": "待匹配项目信息",
                "next_action": "系统将从当前项目和招标文件中继续匹配。",
            }
        return {
            "semantics_recognized": True,
            "resolution_state": "value_resolution_pending",
            "resolution_label": "待匹配对应资料",
            "next_action": "字段含义已识别，系统将继续匹配对应资料。",
        }

    @staticmethod
    def _review_group(
        *,
        definition: VariableDefinition,
        primary: dict[str, Any],
        slots: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Group fields by business object without merging their values."""
        entity_type = definition.target_entity_type
        if entity_type and definition.variable_key.startswith("entity_fact."):
            parts = definition.variable_key.split(".")
            return ".".join(parts[:3]), definition.entity_scope_label
        if entity_type in {"Organization", "Project"}:
            scope = f"{entity_type}|{definition.entity_scope_label}"
            token = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            return f"entity_scope.{token}", definition.entity_scope_label
        slot = slots[0] if slots else {}
        if entity_type == "Person" and (
            slot.get("table_index") is not None
            and slot.get("row") is not None
        ):
            scope = "|".join((
                str(slot.get("document_section") or ""),
                str(slot.get("table_index")),
                str(slot.get("row")),
            ))
            token = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            return f"person_row.{token}", definition.entity_scope_label
        if (
            entity_type in {"BusinessCase", "Certificate", "ResponseItem"}
            or str(primary.get("fill_strategy") or "") in {
                FillStrategy.GENERATED_COLLECTION.value,
                FillStrategy.KNOWLEDGE_COLLECTION.value,
                FillStrategy.AUTO_LAYOUT.value,
            }
        ) and slot.get("table_index") is not None:
            scope = "|".join((
                str(slot.get("document_section") or ""),
                str(slot.get("table_index")),
                entity_type or str(primary.get("fill_strategy") or "table"),
            ))
            token = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            label = {
                "BusinessCase": "企业业绩表（系统整表匹配）",
                "Certificate": "企业证书表（系统整表匹配）",
                "ResponseItem": "招标响应表（系统整表生成）",
            }.get(entity_type, "原模板格式（系统统一处理）")
            return f"table_collection.{token}", label
        if (
            definition.semantic_field == "bid_response.content"
            and slot.get("table_index") is not None
            and slot.get("row") is not None
        ):
            scope = "|".join((
                str(slot.get("document_section") or ""),
                str(slot.get("table_index")),
                str(slot.get("row")),
            ))
            token = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]
            return f"response_row.{token}", (
                f"{slot.get('document_section') or '响应表'}第 {int(slot['row']) + 1} 行"
            )
        return definition.variable_key, definition.entity_scope_label

    @staticmethod
    def _slot_snapshot(decision: dict[str, Any]) -> dict[str, Any]:
        slot = decision.get("slot") or {}
        return {
            "field_key": decision.get("field_key"),
            "label": decision.get("label"),
            "display_name": decision.get("display_name") or decision.get("label"),
            "source_location": (
                slot.get("source_location")
                or decision.get("evidence_location")
                or "原响应模板"
            ),
            "document_section": slot.get("document_section"),
            "table_index": slot.get("table_index"),
            "paragraph_index": slot.get("paragraph_index"),
            "row": slot.get("row"),
            "column": slot.get("column"),
            "surrounding_text": slot.get("surrounding_text"),
        }

    @staticmethod
    def fan_out(variable_decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for variable in variable_decisions:
            for original in variable.get("_field_decisions", ()):
                fields.append({
                    **original,
                    "value": variable.get("value"),
                    "status": variable.get("status"),
                    "reason": variable.get("reason"),
                    "confidence": variable.get("confidence", 0),
                    "source_type": variable.get("source_type"),
                    "source_reference": variable.get("source_reference"),
                    "evidence_title": variable.get("evidence_title"),
                    "evidence_excerpt": variable.get("evidence_excerpt"),
                    "evidence_location": variable.get("evidence_location"),
                    "variable_key": variable.get("variable_key"),
                    "variable_standard_name": variable.get("standard_name"),
                    "variable_slot_count": variable.get("slot_count", 1),
                })
        return fields

    @staticmethod
    def public_snapshot(variable: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in variable.items()
            if key != "_field_decisions"
        }
