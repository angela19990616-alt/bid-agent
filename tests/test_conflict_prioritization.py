from app.core.conflict_detection import ConflictDetectionEngine
from app.core.response_prioritization import ResponsePrioritizationEngine
from app.rules.engine import RuleEngine


def test_scoring_enhancement_is_positive_difference():
    result = ConflictDetectionEngine.compare(
        text_a="采购需求要求合同签订后3个月完成服务。",
        text_b="评分办法规定提前完成可获得加分。",
        role_a="procurement_requirement",
        role_b="scoring_method",
    )
    assert result is not None
    assert result.conflict_type == "positive_difference"


def test_different_service_periods_are_true_conflict():
    result = ConflictDetectionEngine.compare(
        text_a="采购需求规定服务期限为3个月。",
        text_b="合同条款规定服务期限为6个月。",
        role_a="procurement_requirement",
        role_b="contract",
    )
    assert result is not None
    assert result.conflict_type == "true_conflict"
    assert result.risk_priority == "P0"


def test_different_objects_are_not_compared():
    result = ConflictDetectionEngine.compare(
        text_a="整体服务期限为180日历天。",
        text_b="验收时应提交纸质成果5套。",
        role_a="procurement_requirement",
        role_b="contract",
    )
    assert result is None


def test_scored_proposal_item_has_independent_value_and_risk():
    result = ResponsePrioritizationEngine.evaluate(
        text="服务方案应包含团队分工，评分办法对此项计分。",
        response_action="write_into_proposal",
        scoring_impact="score_item",
        importance="high",
        requirement_type="technical_requirement",
        scoring_relation="high_score_item",
    )
    assert result.risk_priority == "P1"
    assert result.proposal_value == 5
    assert result.risk_type is None


def test_non_subcontracting_is_p0_but_not_proposal_value():
    result = ResponsePrioritizationEngine.evaluate(
        text="供应商不得分包或转包服务。",
        response_action="compliance_commitment",
        scoring_impact="penalty_risk",
        importance="critical",
        requirement_type="commercial_requirement",
    )
    assert result.risk_priority == "P0"
    assert result.proposal_value == 0
    assert result.risk_type == "contract"


def test_new_rule_documents_are_loadable():
    assert RuleEngine().load_default("conflict_detection").version == 1
    assert RuleEngine().load_default("response_prioritization").version == 1
