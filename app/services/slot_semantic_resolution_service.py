from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.config.settings import settings
from app.core.entity_resolution import (
    DocumentSlot,
    EntityType,
    FillStrategy,
    ProjectRole,
    SlotContextClassifier,
    SlotSemanticContractValidator,
    SubjectRole,
)
from app.core.model_client import ModelClient


@dataclass(frozen=True)
class SlotSemanticResolutionResult:
    fields: tuple[dict[str, Any], ...]
    actions: tuple[dict[str, Any], ...]
    report: dict[str, Any]


class SlotSemanticResolutionService:
    """Let AI understand a slot, then let the ontology decide what is valid.

    The model never supplies a business value.  It only selects a configured
    business concept and, for people, a project role.  Invalid, low-confidence
    or structurally inconsistent answers retain the deterministic mapping.
    """

    def __init__(self, model_client: ModelClient | None = None):
        self.model_client = model_client

    @staticmethod
    @lru_cache(maxsize=1)
    def _rules() -> dict[str, Any]:
        path = (
            Path(settings.rules_root)
            / "slot_semantic_resolution.default.json"
        )
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("rule_type") != "slot_semantic_resolution":
            raise ValueError("空位语义识别规则类型不正确。")
        return payload

    @classmethod
    def rule_version(cls) -> str:
        return str(cls._rules().get("version") or "unknown")

    def resolve(
        self,
        fields: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        actions: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
        *,
        workflow_run_id: UUID | None = None,
    ) -> SlotSemanticResolutionResult:
        original = [dict(item) for item in fields]
        current_actions = [dict(item) for item in actions]
        rules = self._rules()
        if not rules.get("enabled", True):
            return SlotSemanticResolutionResult(
                tuple(original), tuple(current_actions), self._report(
                    rules, status="disabled", reviewed=0,
                )
            )
        if not original:
            return SlotSemanticResolutionResult(
                (), tuple(current_actions), self._report(
                    rules, status="skipped", reviewed=0,
                )
            )
        groups = self._group_fields(original)
        review_groups = [
            group for group in groups
            if any(self._needs_ai(field, rules) for field in group["fields"])
        ]
        review_group_ids = {
            str(group["group_id"]) for group in review_groups
        }
        decisions: dict[str, dict[str, Any]] = {}
        failure: str | None = None
        if review_groups:
            try:
                client = self.model_client or ModelClient()
                for batch in self._batches(review_groups, rules):
                    payload = self._request_payload(batch, rules)
                    response = client.chat(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "你是投标文件空位语义分析器。"
                                    "只判断空位指向的业务概念，不填写任何值。"
                                    "严格按照给定规则和概念目录返回 JSON。"
                                ),
                            },
                            {
                                "role": "user",
                                "content": json.dumps(
                                    payload, ensure_ascii=False
                                ),
                            },
                        ],
                        temperature=0,
                        max_tokens=4000,
                        task="classification",
                        workflow_run_id=workflow_run_id,
                    )
                    decisions.update(self._parse_response(response))
            except Exception as exc:
                failure = type(exc).__name__

        resolved_fields: list[dict[str, Any]] = []
        applied = rejected = uncertain = 0
        for group in groups:
            decision = decisions.get(group["group_id"])
            for raw in group["fields"]:
                if decision is None:
                    requires_review = group["group_id"] in review_group_ids
                    resolved_fields.append(self._with_resolution(
                        raw, "deterministic_fallback", None,
                        (
                            "AI 未返回该组结果，保留原映射并转人工确认。"
                            if requires_review
                            else "该字段已有高置信本体映射，无需重复调用 AI。"
                        ),
                        requires_human_review=requires_review,
                    ))
                    if requires_review:
                        uncertain += 1
                    continue
                outcome = self._apply_decision(raw, decision, rules)
                if outcome[0] == "action":
                    action = outcome[2]
                    if action is not None:
                        current_actions.append(action)
                    applied += 1
                    continue
                resolved_fields.append(outcome[1])
                if outcome[0] == "applied":
                    applied += 1
                elif outcome[0] == "uncertain":
                    uncertain += 1
                elif outcome[0] == "rejected":
                    rejected += 1

        deduped_actions = self._dedupe_actions(current_actions)
        audit = SlotSemanticContractValidator.audit(resolved_fields)
        status = (
            "failed_fallback" if failure
            else "review_required" if (
                rejected or uncertain or audit.get("status") != "passed"
            )
            else "completed"
        )
        report = self._report(
            rules,
            status=status,
            reviewed=sum(len(group["fields"]) for group in review_groups),
            groups=len(review_groups),
            applied=applied,
            rejected=rejected,
            uncertain=uncertain,
            failure=failure,
            audit=audit,
        )
        return SlotSemanticResolutionResult(
            tuple(resolved_fields), tuple(deduped_actions), report
        )

    @staticmethod
    def _needs_ai(field: dict[str, Any], rules: dict[str, Any]) -> bool:
        confidence = SlotSemanticResolutionService._confidence(
            field.get("confidence")
        )
        if confidence < float(rules.get("review_confidence_below", 0.9)):
            return True
        if field.get("fill_strategy") == FillStrategy.UNRESOLVED.value:
            return True
        label = re.sub(
            r"[：:()（）_＿\s]", "",
            str(field.get("label") or field.get("display_name") or ""),
        )
        return label in {
            re.sub(r"[：:()（）_＿\s]", "", str(item))
            for item in rules.get("ambiguous_labels", ())
        }

    @staticmethod
    def _group_fields(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for field in fields:
            label = re.sub(
                r"\s+", "", str(field.get("label") or field.get("display_name") or "")
            )
            section = re.sub(r"\s+", "", str(field.get("document_section") or ""))
            context = re.sub(
                r"【当前空位：[^】]*】", "【当前空位】",
                str(field.get("surrounding_text") or ""),
            )
            context = re.sub(r"\s+", "", context)[:700]
            coordinate = (
                ":".join((
                    "table",
                    str(field.get("table_index")),
                    str(field.get("column")),
                    context,
                ))
                if field.get("table_index") is not None
                else context
            )
            grouped.setdefault((label, section, coordinate), []).append(field)
        return [
            {
                "group_id": f"G{index:03d}",
                "fields": values,
                "representative": values[0],
            }
            for index, values in enumerate(grouped.values(), start=1)
        ]

    @staticmethod
    def _batches(
        groups: list[dict[str, Any]], rules: dict[str, Any]
    ) -> list[list[dict[str, Any]]]:
        max_groups = max(1, int(rules.get("batch_size", 24)))
        max_chars = max(2000, int(rules.get("max_input_chars", 18000)))
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_chars = 0
        for group in groups:
            estimate = len(json.dumps(
                SlotSemanticResolutionService._public_group(group),
                ensure_ascii=False,
            ))
            if current and (
                len(current) >= max_groups
                or current_chars + estimate > max_chars
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(group)
            current_chars += estimate
        if current:
            batches.append(current)
        return batches

    @staticmethod
    def _public_group(group: dict[str, Any]) -> dict[str, Any]:
        field = group["representative"]
        return {
            "group_id": group["group_id"],
            "same_form_location_count": len(group["fields"]),
            "section": field.get("document_section"),
            "location": field.get("source_location"),
            "label": field.get("label") or field.get("display_name"),
            "surrounding_text": field.get("surrounding_text"),
            "table": {
                "index": field.get("table_index"),
                "row": field.get("row"),
                "column": field.get("column"),
            },
            "current_mapping": {
                "semantic_field": field.get("semantic_field"),
                "entity_type": field.get("expected_entity_type"),
                "role": field.get("expected_role"),
                "value_type": field.get("expected_value_type"),
                "display_name": field.get("display_name"),
            },
        }

    @staticmethod
    def _request_payload(
        batch: list[dict[str, Any]], rules: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "task": "结合完整上下文为每组空位选择业务概念和项目角色",
            "rules": list(rules.get("instructions") or ()),
            "allowed_concepts": {
                key: {
                    "semantic_field": value.get("semantic_field"),
                    "display_name": (
                        value.get("display_name")
                        or value.get("attribute_label")
                        or "文档动作"
                    ),
                    "entity_type": value.get("entity_type"),
                    "person_role_required": (
                        value.get("entity_type") == "Person"
                    ),
                }
                for key, value in (rules.get("concepts") or {}).items()
            },
            "allowed_roles": [role.value for role in ProjectRole],
            "output_schema": {
                "slots": [{
                    "group_id": "G001",
                    "concept_id": "allowed_concepts 的键，或 keep_existing/uncertain",
                    "role": "人员概念填写 allowed_roles；其他为 null",
                    "confidence": "0 到 1",
                    "reason": "一句可读的判断依据"
                }]
            },
            "slots": [
                SlotSemanticResolutionService._public_group(group)
                for group in batch
            ],
        }

    @staticmethod
    def _parse_response(value: str) -> dict[str, dict[str, Any]]:
        cleaned = value.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型未返回空位语义 JSON。")
        payload = json.loads(cleaned[start:end + 1])
        slots = payload.get("slots")
        if not isinstance(slots, list):
            raise ValueError("模型 JSON 缺少 slots 数组。")
        return {
            str(item["group_id"]): item
            for item in slots
            if isinstance(item, dict) and item.get("group_id")
        }

    def _apply_decision(
        self,
        raw: dict[str, Any],
        decision: dict[str, Any],
        rules: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        confidence = self._confidence(decision.get("confidence"))
        reason = str(decision.get("reason") or "AI 未提供判断依据。")[:300]
        concept_id = str(decision.get("concept_id") or "uncertain")
        if concept_id == "keep_existing":
            if confidence < float(rules.get("min_apply_confidence", 0.9)):
                return (
                    "rejected",
                    self._with_resolution(
                        raw,
                        "deterministic_fallback",
                        confidence,
                        reason,
                        requires_human_review=True,
                    ),
                    None,
                )
            return (
                "kept",
                self._with_resolution(raw, "ai_confirmed", confidence, reason),
                None,
            )
        if concept_id == "uncertain":
            return (
                "uncertain",
                self._with_resolution(
                    raw,
                    "human_review_required",
                    confidence,
                    reason,
                    requires_human_review=True,
                ),
                None,
            )
        concept = (rules.get("concepts") or {}).get(concept_id)
        if not isinstance(concept, dict) or confidence < float(
            rules.get("min_apply_confidence", 0.78)
        ):
            return (
                "rejected",
                self._with_resolution(
                    raw,
                    "deterministic_fallback",
                    confidence,
                    reason,
                    requires_human_review=True,
                ),
                None,
            )
        if concept.get("action"):
            return self._apply_action(raw, confidence, reason, rules)
        try:
            candidate = self._candidate_slot(raw, concept, decision, confidence)
        except (KeyError, TypeError, ValueError):
            return (
                "rejected",
                self._with_resolution(
                    raw,
                    "deterministic_fallback",
                    confidence,
                    reason,
                    requires_human_review=True,
                ),
                None,
            )
        snapshot = candidate.snapshot()
        if SlotSemanticContractValidator.audit([snapshot])["status"] != "passed":
            return (
                "rejected",
                self._with_resolution(
                    raw,
                    "deterministic_fallback",
                    confidence,
                    reason,
                    requires_human_review=True,
                ),
                None,
            )
        snapshot.update({
            key: value for key, value in raw.items()
            if key not in snapshot
        })
        return (
            "applied",
            self._with_resolution(snapshot, "ai_resolved", confidence, reason),
            None,
        )

    @staticmethod
    def _candidate_slot(
        raw: dict[str, Any],
        concept: dict[str, Any],
        decision: dict[str, Any],
        confidence: float,
    ) -> DocumentSlot:
        original = DocumentSlot.from_snapshot(raw)
        entity_value = concept.get("entity_type")
        entity_type = EntityType(entity_value) if entity_value else None
        role = None
        if entity_type is EntityType.PERSON:
            role_value = decision.get("role")
            role = ProjectRole(role_value) if role_value else None
            if role is None and original.table_index is None:
                raise ValueError("表外人员空位缺少项目角色。")
        subject_value = concept.get("subject_role")
        subject_role = SubjectRole(subject_value) if subject_value else (
            SubjectRole.CURRENT_PROJECT
            if entity_type is EntityType.PERSON else original.subject_role
        )
        attribute_label = str(concept.get("attribute_label") or "")
        if entity_type is EntityType.PERSON:
            role_label = (
                SlotSemanticResolutionService._rules()
                .get("role_labels", {}).get(role.value)
                if role else "人员清单"
            )
            display_name = f"{role_label}{attribute_label}"
            relation_path = (
                "当前项目", str(role_label), attribute_label,
            ) if role else (
                "当前项目", "投标文件", "人员清单", attribute_label,
            )
            canonical_key = (
                SlotContextClassifier.ROLE_FIELDS[role]
                if role and concept.get("semantic_field") == "person.name"
                else str(concept["canonical_key"])
            )
        else:
            display_name = str(concept["display_name"])
            relation_path = tuple(concept["relation_path"])
            canonical_key = str(concept["canonical_key"])
        semantic_field = str(concept["semantic_field"])
        return replace(
            original,
            semantic_field=semantic_field,
            canonical_key=canonical_key,
            expected_entity_type=entity_type,
            expected_role=role,
            expected_value_type=str(concept["value_type"]),
            confidence=confidence,
            ontology_concept=(
                f"{entity_value or 'BidResponseDocument'}."
                f"{semantic_field.rsplit('.', 1)[-1]}"
            ),
            display_name=display_name,
            subject_role=subject_role,
            relation_path=relation_path,
            value_expression=None,
            fill_strategy=FillStrategy(str(concept["fill_strategy"])),
        )

    @staticmethod
    def _apply_action(
        raw: dict[str, Any],
        confidence: float,
        reason: str,
        rules: dict[str, Any],
    ) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
        label = str(raw.get("label") or raw.get("display_name") or "")
        role_value = raw.get("expected_role")
        role = ProjectRole(role_value) if role_value else None
        action_labels = SlotContextClassifier._required_actions(label, role=role)
        if (
            confidence < float(rules.get("action_min_confidence", 0.92))
            or not action_labels
        ):
            return (
                "rejected",
                SlotSemanticResolutionService._with_resolution(
                    raw,
                    "deterministic_fallback",
                    confidence,
                    reason,
                    requires_human_review=True,
                ),
                None,
            )
        action_name = action_labels[0]
        return (
            "action",
            raw,
            {
                "action_id": f"ai:{raw.get('slot_id') or raw.get('field_key')}",
                "display_name": action_name,
                "source_location": raw.get("source_location") or "原响应模板",
                "surrounding_text": raw.get("surrounding_text") or label,
                "relation_path": ["当前项目", "投标文件", action_name],
                "required_actions": list(action_labels),
                "affected_locations": [
                    raw.get("source_location") or "原响应模板"
                ],
            },
        )

    @staticmethod
    def _with_resolution(
        raw: dict[str, Any], source: str,
        confidence: float | None, reason: str,
        *, requires_human_review: bool = False,
    ) -> dict[str, Any]:
        return {
            **raw,
            "semantic_resolution": {
                "source": source,
                "confidence": confidence,
                "reason": reason,
                "requires_human_review": requires_human_review,
            },
        }

    @staticmethod
    def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for action in actions:
            name = str(action.get("display_name") or "文档动作")
            locations = list(action.get("affected_locations") or ())
            source = action.get("source_location")
            if source and source not in locations:
                locations.append(source)
            if name not in grouped:
                grouped[name] = {**action, "affected_locations": locations}
                continue
            existing = grouped[name]["affected_locations"]
            for location in locations:
                if location not in existing:
                    existing.append(location)
        return list(grouped.values())

    @staticmethod
    def _confidence(value: Any) -> float:
        try:
            return min(1.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _report(
        rules: dict[str, Any], *, status: str, reviewed: int,
        groups: int = 0, applied: int = 0, rejected: int = 0,
        uncertain: int = 0, failure: str | None = None,
        audit: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "rule_version": str(rules.get("version") or "unknown"),
            "reviewed_slot_count": reviewed,
            "reviewed_group_count": groups,
            "applied_slot_count": applied,
            "rejected_slot_count": rejected,
            "uncertain_slot_count": uncertain,
            "failure_type": failure,
            "semantic_audit": audit or {},
        }
