from app.core.requirement_taxonomy import RequirementTaxonomy
from app.core.response_strategy import ResponseStrategyAnalyzer


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

    assert result.requirement_type == "commercial_requirement"
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


def test_team_division_enters_project_organization_chapter():
    result = decide("服务方案应包含团队分工")

    assert result.requirement_type == "technical_requirement"
    assert result.response_action == "write_into_proposal"
    assert result.proposal_mapping == "项目组织管理"


def test_confidentiality_commitment_is_compliance_action():
    result = decide("提供保密承诺")

    assert result.requirement_type == "compliance_requirement"
    assert result.response_action == "compliance_commitment"
    assert result.proposal_mapping is None


def test_project_period_is_delivery_requirement_in_plan():
    result = decide("项目实施周期180日历天")

    assert result.requirement_type == "delivery_requirement"
    assert result.response_action == "write_into_proposal"
    assert result.proposal_mapping == "实施计划"


def test_document_structure_is_a_separate_requirement_type():
    result = decide("响应文件组成及章节顺序必须符合采购文件")

    assert result.requirement_type == "document_structure_requirement"
    assert result.response_action == "risk_notice"
    assert result.proposal_mapping is None


def test_manual_switch_to_proposal_infers_a_useful_chapter():
    result = ResponseStrategyAnalyzer.manual_override(
        target="proposal",
        text="服务方案应说明项目团队职责和人员分工",
    )

    assert result.requirement_type == "technical_requirement"
    assert result.response_action == "write_into_proposal"
    assert result.proposal_mapping == "项目组织管理"


def test_manual_switch_to_compliance_removes_proposal_mapping():
    result = ResponseStrategyAnalyzer.manual_override(
        target="compliance",
        text="供应商应作出书面承诺",
    )

    assert result.requirement_type == "compliance_requirement"
    assert result.response_action == "compliance_commitment"
    assert result.proposal_mapping is None
