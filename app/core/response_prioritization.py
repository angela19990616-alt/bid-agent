from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrioritizationDecision:
    risk_priority: str
    proposal_value: int
    risk_type: str | None


class ResponsePrioritizationEngine:
    """Keeps bid risk and proposal-writing value as separate dimensions."""

    P0_EVIDENCE = (
        "无效投标", "废标", "否决投标", "资格不通过",
        "实质性响应", "不得分包", "不得转包",
    )

    @classmethod
    def evaluate(
        cls,
        *,
        text: str,
        response_action: str,
        scoring_impact: str,
        importance: str,
        requirement_type: str,
        scoring_relation: str = "unknown",
    ) -> PrioritizationDecision:
        in_proposal = response_action == "write_into_proposal"
        has_score_source = (
            scoring_impact == "score_item"
            or scoring_relation in {"high_score_item", "medium_score_item"}
        )
        if not in_proposal:
            value = 0
        elif has_score_source:
            value = 5
        elif any(word in text for word in ("详细方案", "专项方案", "重点论述")):
            value = 4
        elif importance in {"critical", "high"}:
            value = 4
        elif importance == "medium":
            value = 3
        else:
            value = 1

        has_p0_evidence = any(word in text for word in cls.P0_EVIDENCE)
        risk_type = None
        if has_p0_evidence or scoring_impact == "qualification_pass":
            priority = "P0"
            if requirement_type == "qualification_requirement":
                risk_type = "qualification"
            elif requirement_type == "commercial_requirement":
                risk_type = "contract"
            elif requirement_type == "delivery_requirement":
                risk_type = "delivery"
            else:
                risk_type = "disqualification"
        elif has_score_source:
            priority = "P1"
        elif in_proposal:
            priority = "P2"
        else:
            priority = "P3"
        return PrioritizationDecision(priority, value, risk_type)
