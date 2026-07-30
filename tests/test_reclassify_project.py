from scripts.reclassify_project import proposal_relevance


def test_reclassification_keeps_compliance_out_of_proposal():
    assert proposal_relevance("critical", "high_score_item", False) == "low"


def test_reclassification_prioritizes_important_proposal_items():
    assert proposal_relevance("high", "requirement_only", True) == "high"
    assert proposal_relevance("medium", "high_score_item", True) == "high"
    assert proposal_relevance("medium", "requirement_only", True) == "medium"
