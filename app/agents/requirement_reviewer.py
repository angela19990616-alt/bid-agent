from __future__ import annotations

from dataclasses import dataclass

from app.agents.requirement_agent import AgentRequirement
from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class ReviewedRequirement:
    item: AgentRequirement
    proposal_relevance: str
    target_chapter: str | None
    need_generation: bool


class RequirementReviewer:
    """Applies the loaded extraction rules without autonomous loops."""

    def review(
        self,
        items: list[AgentRequirement],
        rules: RuleDocument | None = None,
    ) -> list[ReviewedRequirement]:
        active = rules or RuleEngine().load("extraction")
        return [self.review_one(item, active) for item in items]

    @staticmethod
    def review_one(
        item: AgentRequirement,
        rules: RuleDocument | None = None,
    ) -> ReviewedRequirement:
        active = rules or RuleEngine().load_default("extraction")
        config = active.content
        text = f"{item.title} {item.normalized_text} {item.quote}"
        compliance_only = item.requirement_type in set(
            config["compliance_only_types"]
        )
        if compliance_only:
            return ReviewedRequirement(item, "low", None, False)

        if item.requirement_type == "scoring":
            return ReviewedRequirement(
                item, "high", "技术评分点响应", True
            )

        chapter = None
        relevance = "medium"
        for mapping in config["proposal_mapping"]:
            allowed_types = set(
                mapping.get(
                    "requirement_types",
                    ["technical", "delivery"],
                )
            )
            if item.requirement_type not in allowed_types:
                continue
            if any(keyword in text for keyword in mapping["keywords"]):
                chapter = mapping["target_chapter"]
                relevance = mapping.get("relevance", "high")
                break

        if item.requirement_type in {"technical", "delivery"}:
            return ReviewedRequirement(
                item,
                relevance if chapter else "high",
                chapter or "服务范围与工作内容",
                True,
            )
        if chapter:
            return ReviewedRequirement(item, relevance, chapter, True)
        return ReviewedRequirement(item, "low", None, False)
