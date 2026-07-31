from __future__ import annotations

from dataclasses import dataclass

from app.rules.engine import RuleDocument, RuleEngine


@dataclass(frozen=True)
class ResponseStrategyDecision:
    requirement_type: str
    response_action: str
    proposal_mapping: str | None
    scoring_impact: str
    priority: str


class ResponseStrategyAnalyzer:
    """Turns semantic classification into an actionable bid response."""

    @classmethod
    def analyze(
        cls,
        *,
        legacy_type: str,
        proposal_chapter: str | None,
        scoring_relation: str,
        importance: str,
        text: str,
        rules: RuleDocument | None = None,
    ) -> ResponseStrategyDecision:
        config = (
            rules or RuleEngine().load_default("response_strategy")
        ).content
        for rule in config["hard_rules"]:
            if any(keyword in text for keyword in rule["keywords"]):
                return ResponseStrategyDecision(
                    rule["requirement_type"],
                    rule["response_action"],
                    rule["proposal_mapping"],
                    rule["scoring_impact"],
                    rule["priority"],
                )

        requirement_type = config["legacy_type_mapping"].get(
            legacy_type,
            legacy_type
            if legacy_type in config["type_defaults"]
            else "compliance_requirement",
        )
        if any(
            keyword in text
            for keyword in config["document_structure_keywords"]
        ):
            requirement_type = "document_structure_requirement"
        elif any(
            keyword in text for keyword in config["format_keywords"]
        ):
            requirement_type = "format_requirement"

        defaults = config["type_defaults"][requirement_type]
        action = defaults["response_action"]
        mapping = (
            proposal_chapter or defaults.get("proposal_mapping")
            if action == "write_into_proposal"
            else None
        )
        impact = defaults["scoring_impact"]
        if scoring_relation in {
            "high_score_item",
            "medium_score_item",
        } and action == "write_into_proposal":
            impact = "score_item"

        policy = config["priority_policy"]
        if impact in {"penalty_risk", "qualification_pass"}:
            priority = policy[impact]
        elif impact == "score_item":
            priority = policy["score_item"]
        elif action == "write_into_proposal":
            priority = policy["proposal_quality"]
        else:
            priority = (
                "P0" if importance == "critical"
                else policy["general"]
            )
        return ResponseStrategyDecision(
            requirement_type,
            action,
            mapping,
            impact,
            priority,
        )

    @classmethod
    def manual_override(
        cls,
        *,
        target: str,
        text: str,
        importance: str = "medium",
        rules: RuleDocument | None = None,
    ) -> ResponseStrategyDecision:
        config = (
            rules or RuleEngine().load_default("response_strategy")
        ).content
        if target == "compliance":
            return ResponseStrategyDecision(
                "compliance_requirement",
                "compliance_commitment",
                None,
                "penalty_risk" if importance == "critical" else "no_score",
                "P0" if importance == "critical" else "P3",
            )
        chapter = next(
            (
                item["chapter"]
                for item in config["manual_proposal_chapters"]
                if any(keyword in text for keyword in item["keywords"])
            ),
            config["manual_default_chapter"],
        )
        return ResponseStrategyDecision(
            "technical_requirement",
            "write_into_proposal",
            chapter,
            "no_score",
            "P2",
        )
