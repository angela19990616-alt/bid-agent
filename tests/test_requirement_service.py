from uuid import uuid4

from app.agents.requirement_agent import AgentRequirement
from app.services.requirement_service import RequirementService


def item(
    text: str,
    *,
    title: str = "响应文件有效期要求",
    confidence: float = 0.9,
):
    return AgentRequirement(
        source_id=uuid4(),
        title=title,
        normalized_text=text,
        quote=text,
        requirement_type="compliance",
        importance="high",
        confidence=confidence,
    )


def test_semantic_duplicates_are_merged_with_all_sources():
    first = item("供应商应在响应文件中载明不少于90天的有效期。")
    second = item(
        "响应文件中应载明有效期，且有效期不得少于90天。",
        confidence=0.95,
    )

    result = RequirementService._deduplicate([first, second])

    assert len(result) == 1
    assert set(result[0].source_ids) == {
        first.source_id,
        second.source_id,
    }
    assert result[0].confidence == 0.95


def test_distinct_requirements_are_not_merged():
    result = RequirementService._deduplicate(
        [
            item("供应商应在响应文件中载明不少于90天的有效期。"),
            item(
                "供应商应提交依法缴纳社会保障资金的证明材料。",
                title="提交社保缴纳证明",
            ),
        ]
    )

    assert len(result) == 2


def test_source_mismatch_feedback_key_ignores_spacing_and_case():
    assert RequirementService._feedback_key(" 支持 QWEN 模型\n") == (
        RequirementService._feedback_key("支持qwen模型")
    )


def test_feedback_reason_is_recovered_from_human_marker():
    assert RequirementService._feedback_from_row(
        "rejected",
        "human_feedback:classification_error",
    ) == "classification_error"
    assert RequirementService._feedback_from_row(
        "rejected",
        "human_feedback:duplicate",
    ) == "duplicate"
    assert RequirementService._feedback_from_row(
        "rejected",
        "human_feedback:incomplete",
    ) == "incomplete"


def test_legacy_rejected_requirement_defaults_to_not_needed():
    assert RequirementService._feedback_from_row(
        "rejected",
        None,
    ) == "not_needed"
