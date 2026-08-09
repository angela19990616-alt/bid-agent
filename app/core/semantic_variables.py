from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.entity_resolution import DocumentSlot, FillStrategy


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

        for item in content.get("variables", ()):  # configured exact facts
            aliases = {str(value) for value in item.get("aliases", ())}
            if (
                item.get("semantic_field") == slot.semantic_field
                or slot.canonical_key in aliases
            ):
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

        # Never merge two unresolved people merely because both say "姓名".
        # Until a role exists they are distinct business questions.
        if slot.semantic_field.startswith("person."):
            return cls._fallback(slot, priorities, unique=True)
        return cls._fallback(slot, priorities, unique=False)

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
            return f"待绑定{slot.expected_entity_type.value}"
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
        target_relations = list(dict.fromkeys(
            item[0].target_relation
            for item in items if item[0].target_relation
        ))
        standard_name = definition.standard_name
        if definition.target_entity_type == "Person" and len(target_relations) > 1:
            standard_name = f"同一已绑定人员{primary.get('expected_value_type_label', '属性')}"
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
            "binding_status": primary.get("binding_status"),
            "relation_path": primary.get("relation_path") or [],
            "entity_candidates": primary.get("entity_candidates") or [],
            "fill_strategy": primary.get("fill_strategy") or "unresolved",
            "personnel_rule_results": primary.get("personnel_rule_results") or [],
            "_field_decisions": decisions,
        }

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
