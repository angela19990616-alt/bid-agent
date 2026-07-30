from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxonomyDecision:
    requirement_type: str
    response_action: str
    proposal_mapping: str | None
    scoring_impact: str
    priority: str


class RequirementTaxonomy:
    """Converts semantic classification into independent response dimensions."""

    TECHNICAL_TYPES = {
        "technical_capability",
        "functional_requirement",
        "system_architecture",
        "security_requirement",
        "performance_requirement",
        "implementation_requirement",
        "project_management",
        "operation_maintenance",
        "training_requirement",
        "technical",
    }
    FORMAT_WORDS = {
        "目录格式", "章节顺序", "编制格式", "字体", "字号",
        "行距", "页数", "字数", "装订", "签章",
    }
    SUBCONTRACT_WORDS = {"不得分包", "禁止分包", "不得转包", "禁止转包"}

    @classmethod
    def decide(
        cls,
        *,
        legacy_type: str,
        proposal_chapter: str | None,
        scoring_relation: str,
        importance: str,
        text: str,
    ) -> TaxonomyDecision:
        priority = {
            "critical": "P0",
            "high": "P1",
            "medium": "P2",
            "low": "P3",
        }.get(importance, "P2")

        if any(word in text for word in cls.SUBCONTRACT_WORDS):
            return TaxonomyDecision(
                "compliance_requirement",
                "compliance_commitment",
                None,
                "penalty_risk",
                "P0",
            )
        if legacy_type in {"scoring_requirement", "scoring"}:
            return TaxonomyDecision(
                "scoring_requirement",
                "write_into_proposal" if proposal_chapter else "risk_notice",
                proposal_chapter,
                "score_item",
                "P0" if importance == "critical" else "P1",
            )
        if legacy_type in {"qualification_requirement", "qualification"}:
            return TaxonomyDecision(
                "qualification_requirement",
                "provide_attachment",
                None,
                "qualification_pass",
                priority,
            )
        if legacy_type in {"commercial_requirement", "commercial"}:
            return TaxonomyDecision(
                "commercial_requirement",
                "compliance_commitment",
                None,
                "penalty_risk" if importance == "critical" else "no_score",
                priority,
            )
        if legacy_type in {"delivery_requirement", "delivery"}:
            return TaxonomyDecision(
                "delivery_requirement",
                "write_into_proposal" if proposal_chapter else "write_into_response_table",
                proposal_chapter,
                "no_score",
                priority,
            )
        if legacy_type in cls.TECHNICAL_TYPES:
            return TaxonomyDecision(
                "technical_requirement",
                "write_into_proposal" if proposal_chapter else "write_into_response_table",
                proposal_chapter,
                (
                    "score_item"
                    if scoring_relation in {"high_score_item", "medium_score_item"}
                    else "no_score"
                ),
                priority,
            )
        if any(word in text for word in cls.FORMAT_WORDS):
            return TaxonomyDecision(
                "format_requirement",
                "risk_notice",
                None,
                "penalty_risk",
                priority,
            )
        return TaxonomyDecision(
            "compliance_requirement",
            "compliance_commitment",
            None,
            "penalty_risk" if importance == "critical" else "no_score",
            priority,
        )
