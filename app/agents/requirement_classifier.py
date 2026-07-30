from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from app.agents.requirement_agent import AgentRequirement
from app.core.model_client import ModelClient
from app.rules.engine import RuleDocument, RuleEngine


SCORING_RELATIONS = {
    "high_score_item", "medium_score_item", "requirement_only", "unknown"
}
IMPORTANCE_LEVELS = {"low", "medium", "high", "critical"}


@dataclass(frozen=True)
class ClassifiedRequirement:
    item: AgentRequirement
    requirement_type: str
    proposal_chapter: str | None
    scoring_relation: str
    importance: str
    confidence: float
    knowledge_support_required: bool
    rationale: str
    conflict: bool = False


class RequirementClassifier:
    """One bounded proposal-oriented classification pass with rule fallback."""

    def __init__(self, model_client: ModelClient | None = None):
        self.model_client = model_client

    def classify(
        self,
        items: list[AgentRequirement],
        rules: RuleDocument | None = None,
    ) -> list[ClassifiedRequirement]:
        active = rules or RuleEngine().load("classification")
        fallback = [
            self.classify_by_rules(item, active) for item in items
        ]
        ambiguous_indexes = [
            index for index, item in enumerate(fallback)
            if (
                item.confidence < 0.8
                or item.proposal_chapter is None
            )
            and item.requirement_type not in {
                "qualification_requirement", "commercial_requirement"
            }
        ]
        if not ambiguous_indexes:
            return fallback
        ambiguous_items = [items[index] for index in ambiguous_indexes]
        try:
            response = (self.model_client or ModelClient()).chat(
                [
                    {
                        "role": "system",
                        "content": (
                            active.content["model_instruction"] + "\n"
                            "本次加载的版本化分类规则如下：\n"
                            + json.dumps(
                                active.content, ensure_ascii=False
                            )
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            [
                                {
                                    "source_ref": f"R{index}",
                                    "title": item.title,
                                    "requirement": item.normalized_text,
                                    "evidence": item.quote,
                                    "extraction_type": item.requirement_type,
                                }
                                for index, item in enumerate(
                                    ambiguous_items, 1
                                )
                            ],
                            ensure_ascii=False,
                        ),
                    },
                ],
                temperature=0,
                max_tokens=5000,
                task="classification",
            )
            payload = self._parse_json(response)
        except Exception:
            return fallback

        by_ref = {
            str(raw.get("source_ref")): raw
            for raw in payload.get("classifications", [])
            if isinstance(raw, dict)
        }
        results = list(fallback)
        for model_index, original_index in enumerate(
            ambiguous_indexes, 1
        ):
            raw = by_ref.get(f"R{model_index}")
            if raw:
                results[original_index] = self._model_result(
                    fallback[original_index], raw, active
                )
        return results

    @classmethod
    def classify_by_rules(
        cls,
        item: AgentRequirement,
        rules: RuleDocument | None = None,
    ) -> ClassifiedRequirement:
        active = rules or RuleEngine().load_default("classification")
        config = active.content
        text = f"{item.title} {item.normalized_text} {item.quote}"
        matches = sorted(
            config["classifiers"],
            key=lambda rule: int(rule.get("priority", 0)),
            reverse=True,
        )
        selected = next(
            (
                rule for rule in matches
                if any(word in text for word in rule["keywords"])
            ),
            None,
        )
        if selected is None:
            selected = {
                "type": cls._legacy_type(item.requirement_type),
                "chapter": None,
                "need_generation": False,
            }
        requirement_type = selected["type"]
        definition = config["requirement_types"][requirement_type]
        chapter = (
            selected.get("chapter")
            if "chapter" in selected
            else definition.get("default_chapter")
        )
        need_generation = bool(
            selected.get("need_generation", chapter is not None)
        )
        if not need_generation:
            chapter = None
        scoring_relation = cls._scoring_relation(text, config)
        importance = cls._importance(text, item.importance, config)
        confidence = 0.88 if selected.get("keywords") else 0.55
        knowledge_required = any(
            word in text for word in config.get("knowledge_keywords", [])
        )
        return ClassifiedRequirement(
            item=item,
            requirement_type=requirement_type,
            proposal_chapter=chapter,
            scoring_relation=scoring_relation,
            importance=importance,
            confidence=confidence,
            knowledge_support_required=knowledge_required,
            rationale="依据版本化分类规则完成方案章节映射。",
        )

    @classmethod
    def _model_result(
        cls,
        fallback: ClassifiedRequirement,
        raw: dict,
        rules: RuleDocument,
    ) -> ClassifiedRequirement:
        config = rules.content
        requirement_type = str(raw.get("requirement_type", ""))
        if requirement_type not in config["requirement_types"]:
            return fallback
        chapter = raw.get("proposal_chapter")
        if chapter is not None:
            chapter = str(chapter).strip() or None
        if requirement_type in {
            "qualification_requirement", "commercial_requirement"
        }:
            chapter = None
        scoring = str(raw.get("scoring_relation", "unknown"))
        importance = str(raw.get("importance", fallback.importance))
        try:
            confidence = float(raw.get("confidence", 0))
        except (TypeError, ValueError):
            return fallback
        if scoring not in SCORING_RELATIONS:
            scoring = fallback.scoring_relation
        if importance not in IMPORTANCE_LEVELS:
            importance = fallback.importance
        return ClassifiedRequirement(
            item=fallback.item,
            requirement_type=requirement_type,
            proposal_chapter=chapter,
            scoring_relation=scoring,
            importance=importance,
            confidence=min(max(confidence, 0.0), 1.0),
            knowledge_support_required=bool(
                raw.get(
                    "knowledge_support_required",
                    fallback.knowledge_support_required,
                )
            ),
            rationale=str(raw.get("rationale", "")).strip()[:500],
        )

    @staticmethod
    def _legacy_type(value: str) -> str:
        return {
            "technical": "technical_capability",
            "scoring": "scoring_requirement",
            "delivery": "delivery_requirement",
            "qualification": "qualification_requirement",
            "commercial": "commercial_requirement",
            "compliance": "other",
        }.get(value, value if value else "other")

    @staticmethod
    def _scoring_relation(text: str, config: dict) -> str:
        for relation in ("high_score_item", "medium_score_item"):
            if any(
                word in text
                for word in config["scoring_keywords"].get(relation, [])
            ):
                return relation
        return "requirement_only"

    @staticmethod
    def _importance(text: str, current: str, config: dict) -> str:
        for level in ("critical", "high", "medium"):
            if any(
                word in text
                for word in config["importance_keywords"].get(level, [])
            ):
                return level
        return current if current in IMPORTANCE_LEVELS else "low"

    @staticmethod
    def _parse_json(value: str) -> dict:
        cleaned = value.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return json.loads(cleaned)


class ClassificationReviewer:
    """Deterministic second pass; rules win over unsafe model routing."""

    def review(
        self,
        items: list[ClassifiedRequirement],
        rules: RuleDocument | None = None,
    ) -> list[ClassifiedRequirement]:
        active = rules or RuleEngine().load("classification")
        return [self.review_one(item, active) for item in items]

    @staticmethod
    def review_one(
        item: ClassifiedRequirement,
        rules: RuleDocument | None = None,
    ) -> ClassifiedRequirement:
        active = rules or RuleEngine().load_default("classification")
        rule_result = RequirementClassifier.classify_by_rules(
            item.item, active
        )
        conflict = False
        final = item
        strong_rule = rule_result.confidence >= 0.8
        if strong_rule and (
            item.requirement_type != rule_result.requirement_type
            or item.proposal_chapter != rule_result.proposal_chapter
        ):
            conflict = True
            final = replace(
                item,
                requirement_type=rule_result.requirement_type,
                proposal_chapter=rule_result.proposal_chapter,
                knowledge_support_required=(
                    item.knowledge_support_required
                    or rule_result.knowledge_support_required
                ),
                rationale=(
                    "分类 Reviewer 检测到冲突，已按高优先级规则纠正。"
                ),
            )
        if final.requirement_type in {
            "qualification_requirement", "commercial_requirement"
        }:
            if final.proposal_chapter is not None:
                conflict = True
            final = replace(final, proposal_chapter=None)
        elif final.proposal_chapter is None:
            default = active.content["requirement_types"][
                final.requirement_type
            ].get("default_chapter")
            if default:
                conflict = True
                final = replace(final, proposal_chapter=default)
        return replace(
            final,
            confidence=min(
                max(
                    final.confidence - (0.12 if conflict else 0),
                    0.5,
                ),
                0.98,
            ),
            conflict=conflict,
        )
