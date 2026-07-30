from dataclasses import replace
from uuid import uuid4

from app.agents.output_quality import (
    OutputReviewAgent,
    ReviewedDebugPipeline,
)
from app.agents.requirement_agent import AgentRequirement
from app.agents.requirement_classifier import (
    ClassificationReviewer,
    RequirementClassifier,
)
from app.agents.proposal_planner import ProposalPlanner
from app.rules.engine import RuleEngine
from app.services.proposal_review_service import ProposalReviewService


def requirement(text: str, legacy_type: str = "technical"):
    return AgentRequirement(
        source_id=uuid4(),
        title=text[:30],
        normalized_text=text,
        quote=text,
        requirement_type=legacy_type,
        importance="medium",
        confidence=0.9,
    )


def classify(text: str, legacy_type: str = "technical"):
    rules = RuleEngine().load_default("classification")
    initial = RequirementClassifier.classify_by_rules(
        requirement(text, legacy_type), rules
    )
    return ClassificationReviewer().review_one(initial, rules)


def test_function_controls_map_to_system_function_design():
    result = classify("系统支持用户管理、权限控制、日志审计")
    assert result.requirement_type == "functional_requirement"
    assert result.proposal_chapter == "系统功能设计"


def test_implementation_period_maps_to_implementation_plan():
    result = classify("项目实施周期180日历天")
    assert result.requirement_type == "implementation_requirement"
    assert result.proposal_chapter == "实施计划"


def test_round_the_clock_service_maps_to_operation_maintenance():
    result = classify("提供7×24小时运维服务")
    assert result.requirement_type == "operation_maintenance"
    assert result.proposal_chapter == "运维保障方案"


def test_dishonesty_constraint_is_compliance_only():
    result = classify(
        "供应商不得存在失信情况", legacy_type="qualification"
    )
    assert result.requirement_type == "qualification_requirement"
    assert result.proposal_chapter is None


def test_strong_rule_classification_does_not_call_model():
    class ExplodingClient:
        def chat(self, *_args, **_kwargs):
            raise AssertionError("strong rules must not call model")

    item = requirement("提供7×24小时运维服务")
    result = RequirementClassifier(ExplodingClient()).classify(
        [item], RuleEngine().load_default("classification")
    )
    assert result[0].proposal_chapter == "运维保障方案"


def test_reviewer_corrects_model_conflict_and_marks_it():
    rule_result = classify("项目实施周期180日历天")
    wrong = replace(
        rule_result,
        requirement_type="functional_requirement",
        proposal_chapter="系统功能设计",
    )
    reviewed = ClassificationReviewer().review_one(wrong)
    assert reviewed.requirement_type == "implementation_requirement"
    assert reviewed.proposal_chapter == "实施计划"
    assert reviewed.conflict is True


def test_planner_prefers_proposal_chapter():
    result = ProposalPlanner().plan(
        [{
            "id": uuid4(),
            "proposal_chapter": "实施计划",
            "target_chapter": "旧章节",
            "need_generation": True,
        }],
        RuleEngine().load_default("writing"),
    )
    assert result[0].title == "实施计划"


def test_review_debug_review_removes_internal_labels():
    classified = classify("项目实施周期180日历天")
    polluted = replace(
        classified,
        item=replace(
            classified.item,
            title="（要求代码 REQ-12）项目实施周期",
            normalized_text=(
                "requirement_id: "
                "123e4567-e89b-12d3-a456-426614174000 项目实施周期"
            ),
        ),
    )
    fixed = ReviewedDebugPipeline().run([polluted])[0]
    assert OutputReviewAgent.review(fixed) == []
    assert "REQ-12" not in fixed.item.title
    assert "requirement_id" not in fixed.item.normalized_text


def test_new_scoring_type_is_counted_by_proposal_review():
    item = {
        "public_key": "R0001",
        "type": "scoring_requirement",
        "title": "实施方案评分10分",
        "normalized_text": "实施方案完整可得10分",
        "quote": "实施方案完整可得10分",
        "source_location": "采购文件，第1页",
    }
    report = ProposalReviewService.review(
        {
            "project_name": "测试项目",
            "requirements": [item],
            "sections": [],
        },
        RuleEngine().load_default("compliance"),
        phase="final",
    )
    assert len(report["scoring_coverage"]) == 1
