from app.services.section_service import SectionService


def test_review_blocks_unsupported_claims():
    findings = SectionService.review(
        "我公司拥有大量成功案例，并百分之百保证项目验收。"
    )

    assert any(item.severity == "blocking" for item in findings)


def test_review_does_not_block_technical_terms_without_evidence_context():
    findings = SectionService.review(
        "方案根据采购要求说明云原生部署和信创适配方法。"
    )

    assert not any(
        item.finding_type == "unsupported_specifics"
        for item in findings
    )
    assert not any(item.severity == "blocking" for item in findings)


def test_prompt_requires_evidence_boundary():
    messages = SectionService._messages(
        "实施方案",
        [
            {
                "id": "requirement-1",
                "normalized_text": "系统须支持备份",
                "quote": "系统须支持每日备份。",
            }
        ],
    )

    assert "不得虚构" in messages[0]["content"]
    assert "原文证据" in messages[1]["content"]
    assert "系统须支持每日备份" in messages[1]["content"]


def test_prompt_accepts_refinement_without_overriding_truth_rules():
    messages = SectionService._messages(
        "实施计划",
        [
            {
                "id": "requirement-1",
                "normalized_text": "提交实施计划",
                "quote": "供应商须提交实施计划。",
            }
        ],
        generation_instruction="按准备、实施、验收三个阶段展开。",
    )

    assert "按准备、实施、验收三个阶段展开" in messages[1]["content"]
    assert "不能覆盖事实边界" in messages[1]["content"]


def test_generated_content_removes_internal_requirement_labels():
    content = SectionService.sanitize_generated_content(
        "一、实施安排（要求 123e4567-e89b-12d3-a456-426614174000）\n"
        "Requirements: 分阶段推进。\n"
        "原文证据：供应商须提交实施计划。"
    )

    assert "123e4567" not in content
    assert "Requirements:" not in content
    assert "原文证据：" not in content
    assert "分阶段推进" in content
    assert "供应商须提交实施计划" in content
