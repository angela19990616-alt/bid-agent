from app.core.requirement_taxonomy import RequirementTaxonomy


def decide(text: str, legacy_type: str = "other", chapter=None):
    return RequirementTaxonomy.decide(
        legacy_type=legacy_type,
        proposal_chapter=chapter,
        scoring_relation="requirement_only",
        importance="high",
        text=text,
    )


def test_no_subcontract_clause_is_compliance_penalty_not_scoring():
    result = decide("供应商不得分包或转包服务")

    assert result.requirement_type == "compliance_requirement"
    assert result.response_action == "compliance_commitment"
    assert result.proposal_mapping is None
    assert result.scoring_impact == "penalty_risk"
    assert result.priority == "P0"


def test_technical_requirement_maps_into_proposal_independently():
    result = decide(
        "提供项目实施计划",
        legacy_type="implementation_requirement",
        chapter="实施计划",
    )

    assert result.requirement_type == "technical_requirement"
    assert result.response_action == "write_into_proposal"
    assert result.proposal_mapping == "实施计划"
    assert result.scoring_impact == "no_score"


def test_qualification_requires_attachment_and_pass_check():
    result = decide(
        "提供营业执照",
        legacy_type="qualification_requirement",
    )

    assert result.requirement_type == "qualification_requirement"
    assert result.response_action == "provide_attachment"
    assert result.proposal_mapping is None
    assert result.scoring_impact == "qualification_pass"


def test_format_requirement_is_risk_notice_not_proposal_content():
    result = decide("正文字号应为小四号")

    assert result.requirement_type == "format_requirement"
    assert result.response_action == "risk_notice"
    assert result.proposal_mapping is None
    assert result.scoring_impact == "penalty_risk"
