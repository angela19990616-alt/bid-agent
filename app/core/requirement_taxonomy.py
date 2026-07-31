from __future__ import annotations

from app.core.response_strategy import (
    ResponseStrategyAnalyzer,
    ResponseStrategyDecision,
)


TaxonomyDecision = ResponseStrategyDecision


class RequirementTaxonomy:
    """Compatibility facade for the Response Strategy layer."""

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
        return ResponseStrategyAnalyzer.analyze(
            legacy_type=legacy_type,
            proposal_chapter=proposal_chapter,
            scoring_relation=scoring_relation,
            importance=importance,
            text=text,
        )
