from uuid import uuid4

from app.agents.requirement_agent import AgentRequirement
from app.agents.requirement_normalizer import ResponseItemNormalizer


def requirement(text: str) -> AgentRequirement:
    return AgentRequirement(
        source_id=uuid4(),
        title="服务方案要求",
        normalized_text=text,
        quote=text,
        requirement_type="technical",
        importance="high",
        confidence=0.9,
    )


def test_splits_compound_service_plan_into_response_items():
    result = ResponseItemNormalizer().normalize(
        [
            requirement(
                "供应商应制定服务方案，包括实施计划安排、"
                "重点难点分析、服务质量保证等内容。"
            )
        ]
    )

    assert [item.normalized_text for item in result.items] == [
        "服务方案应包含实施计划安排。",
        "服务方案应包含重点难点分析。",
        "服务方案应包含服务质量保证。",
    ]
    assert result.events[0].operation == "split"
    assert len(result.events[0].output_texts) == 3


def test_does_not_split_normal_sentence_or_oversized_list():
    normal = requirement("供应商须在180日历天内提交成果。")
    oversized = requirement(
        "服务方案包括一项要求、二项要求、三项要求、四项要求、"
        "五项要求、六项要求、七项要求、八项要求、九项要求。"
    )

    result = ResponseItemNormalizer().normalize([normal, oversized])

    assert result.items == (normal, oversized)
    assert [item.operation for item in result.events] == [
        "unchanged",
        "unchanged",
    ]


def test_standardizes_whitespace_without_changing_evidence():
    item = requirement("供应商应  提交成果。\n\n并提供电子版。")

    result = ResponseItemNormalizer().normalize([item])

    assert result.items[0].normalized_text == (
        "供应商应 提交成果。\n并提供电子版。"
    )
    assert result.events[0].operation == "standardize"
