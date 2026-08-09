from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class SemanticEntity:
    key: str
    entity_type: str
    label: str
    mention: str
    resolved: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "type": self.entity_type,
            "label": self.label,
            "mention": self.mention,
            "resolved": self.resolved,
        }


@dataclass(frozen=True)
class SemanticRelation:
    subject: str
    predicate: str
    predicate_label: str
    object: str
    rule_key: str
    confidence: float
    focus_priority: int = 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "predicate_label": self.predicate_label,
            "object": self.object,
            "rule_key": self.rule_key,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SemanticAction:
    actor: str
    action: str
    action_label: str
    target: str | None
    required: bool

    def snapshot(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "action": self.action,
            "action_label": self.action_label,
            "target": self.target,
            "required": self.required,
        }


@dataclass(frozen=True)
class RequirementSemanticGraph:
    entities: tuple[SemanticEntity, ...]
    relations: tuple[SemanticRelation, ...]
    actions: tuple[SemanticAction, ...]
    focus_entity: str | None
    focus_relation: str | None
    focus_summary: str
    material_entities: tuple[str, ...]
    constraints: tuple[str, ...]
    confidence: float
    rule_version: int

    def snapshot(self) -> dict[str, Any]:
        return {
            "entities": [item.snapshot() for item in self.entities],
            "relations": [item.snapshot() for item in self.relations],
            "actions": [item.snapshot() for item in self.actions],
            "focus_entity": self.focus_entity,
            "focus_relation": self.focus_relation,
            "focus_summary": self.focus_summary,
            "material_entities": list(self.material_entities),
            "constraints": list(self.constraints),
            "confidence": self.confidence,
            "rule_version": self.rule_version,
        }


class RequirementRelationEngine:
    """Build a bounded entity-relation view from one sourced requirement.

    The engine does not resolve enterprise facts. It only records roles,
    materials, relations and actions that are explicitly supported by the
    tender text. Missing real people or files remain unresolved by design.
    """

    def __init__(self, rules: RuleDocument | None = None):
        self.rules = rules or RuleEngine().load_default("entity_relation")

    def analyze(self, text: str) -> RequirementSemanticGraph:
        source = " ".join(str(text or "").split())
        config = self.rules.content
        definitions = config["entity_definitions"]
        entities: dict[str, SemanticEntity] = {}

        def add_entity(key: str, mention: str | None = None) -> None:
            if key in entities or key not in definitions:
                return
            definition = definitions[key]
            entities[key] = SemanticEntity(
                key=key,
                entity_type=str(definition["type"]),
                label=str(definition["label"]),
                mention=mention or str(definition["label"]),
            )

        for key, definition in definitions.items():
            mention = next(
                (
                    alias for alias in definition.get("aliases", [])
                    if alias in source
                ),
                None,
            )
            if mention:
                add_entity(key, mention)

        if any(marker in source for marker in ("供应商", "投标人", "响应文件")):
            add_entity("supplier")

        for key, definition in config.get(
            "credential_definitions", {}
        ).items():
            mention = next(
                (
                    alias for alias in definition.get("aliases", [])
                    if alias in source
                ),
                None,
            )
            if mention:
                entities[key] = SemanticEntity(
                    key=key,
                    entity_type="credential",
                    label=str(definition["label"]),
                    mention=mention,
                )

        relations: list[SemanticRelation] = []
        for rule in config["relation_rules"]:
            if not self._rule_matches(source, rule):
                continue
            subject = str(rule["subject"])
            object_key = str(rule["object"])
            add_entity(subject)
            add_entity(object_key)
            if subject not in entities or object_key not in entities:
                continue
            relations.append(
                SemanticRelation(
                    subject=subject,
                    predicate=str(rule["predicate"]),
                    predicate_label=str(rule["predicate_label"]),
                    object=object_key,
                    rule_key=str(rule["key"]),
                    confidence=0.96,
                    focus_priority=int(rule.get("focus_priority", 0)),
                )
            )

        actions = self._actions(source, entities, config)
        relations.extend(self._material_relations(entities, actions, config))
        relations = self._unique_relations(relations)
        focus_relation = max(
            relations,
            key=lambda item: item.focus_priority,
            default=None,
        )
        focus_entity = self._focus_entity(
            entities, focus_relation, config
        )
        material_keys = tuple(
            item.key for item in entities.values()
            if item.entity_type == "evidence_material"
        )
        constraints = tuple(
            action.action_label for action in actions
            if action.action in {"sign", "stamp", "fill"}
        )
        summary = self._summary(
            entities, focus_relation, actions, material_keys, constraints
        )
        explicit = len(relations) + len(actions)
        confidence = min(0.98, 0.55 + explicit * 0.08)
        return RequirementSemanticGraph(
            entities=tuple(entities.values()),
            relations=tuple(relations),
            actions=tuple(actions),
            focus_entity=focus_entity,
            focus_relation=(
                focus_relation.predicate if focus_relation else None
            ),
            focus_summary=summary,
            material_entities=material_keys,
            constraints=tuple(dict.fromkeys(constraints)),
            confidence=round(confidence, 2),
            rule_version=self.rules.version,
        )

    @staticmethod
    def _rule_matches(text: str, rule: dict[str, Any]) -> bool:
        if rule.get("trigger_all") and not all(
            value in text for value in rule["trigger_all"]
        ):
            return False
        if rule.get("trigger_any") and not any(
            value in text for value in rule["trigger_any"]
        ):
            return False
        if rule.get("trigger_groups") and not all(
            any(value in text for value in group)
            for group in rule["trigger_groups"]
        ):
            return False
        return bool(
            rule.get("trigger_all")
            or rule.get("trigger_any")
            or rule.get("trigger_groups")
        )

    @staticmethod
    def _actions(
        text: str,
        entities: dict[str, SemanticEntity],
        config: dict[str, Any],
    ) -> list[SemanticAction]:
        materials = [
            item.key for item in entities.values()
            if item.entity_type == "evidence_material"
        ]
        actions: list[SemanticAction] = []
        required = any(
            marker in text for marker in ("必须", "须", "应", "不得")
        )
        for definition in config["action_definitions"]:
            if not any(
                keyword in text for keyword in definition["keywords"]
            ):
                continue
            action_key = str(definition["key"])
            targets = (
                materials
                if action_key in {"provide", "sign", "stamp", "fill"}
                and materials
                else [None]
            )
            for target in targets:
                actions.append(
                    SemanticAction(
                        actor="supplier",
                        action=action_key,
                        action_label=str(definition["label"]),
                        target=target,
                        required=required,
                    )
                )
        return actions

    @staticmethod
    def _material_relations(
        entities: dict[str, SemanticEntity],
        actions: list[SemanticAction],
        config: dict[str, Any],
    ) -> list[SemanticRelation]:
        generic = config["generic_relations"]
        relations: list[SemanticRelation] = []
        for action in actions:
            if action.action != "provide" or action.target is None:
                continue
            relations.append(
                SemanticRelation(
                    subject=action.actor,
                    predicate=str(generic["material_action_predicate"]),
                    predicate_label=str(generic["material_action_label"]),
                    object=action.target,
                    rule_key="explicit_material_action",
                    confidence=0.92,
                    focus_priority=60,
                )
            )
        return relations

    @staticmethod
    def _unique_relations(
        relations: list[SemanticRelation],
    ) -> list[SemanticRelation]:
        unique: dict[tuple[str, str, str], SemanticRelation] = {}
        for item in relations:
            key = (item.subject, item.predicate, item.object)
            current = unique.get(key)
            if current is None or item.confidence > current.confidence:
                unique[key] = item
        return list(unique.values())

    @staticmethod
    def _focus_entity(
        entities: dict[str, SemanticEntity],
        relation: SemanticRelation | None,
        config: dict[str, Any],
    ) -> str | None:
        if relation is not None:
            subject = entities.get(relation.subject)
            object_item = entities.get(relation.object)
            if object_item and object_item.entity_type == "person_role":
                return object_item.key
            if subject and subject.entity_type == "person_role":
                return subject.key
            return relation.object
        order = config["focus_policy"]["entity_type_order"]
        for entity_type in order:
            match = next(
                (
                    item.key for item in entities.values()
                    if item.entity_type == entity_type
                ),
                None,
            )
            if match:
                return match
        return None

    @staticmethod
    def _summary(
        entities: dict[str, SemanticEntity],
        relation: SemanticRelation | None,
        actions: list[SemanticAction],
        material_keys: tuple[str, ...],
        constraints: tuple[str, ...],
    ) -> str:
        parts: list[str] = []
        if relation is not None:
            parts.append(
                f"核心关系：{entities[relation.subject].label}"
                f"{relation.predicate_label}{entities[relation.object].label}"
            )
        if material_keys:
            parts.append(
                "所需材料："
                + "、".join(entities[key].label for key in material_keys)
            )
        primary_actions = [
            item.action_label for item in actions
            if item.action not in {"sign", "stamp", "fill"}
        ]
        if primary_actions:
            parts.append("响应动作：" + "、".join(dict.fromkeys(primary_actions)))
        if constraints:
            parts.append("办理约束：" + "、".join(dict.fromkeys(constraints)))
        return "；".join(parts) or "未识别出明确实体关系，需人工复核原文。"
