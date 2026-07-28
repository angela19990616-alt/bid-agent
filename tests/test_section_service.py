from app.services.section_service import SectionService


def test_review_blocks_unsupported_claims():
    findings = SectionService.review(
        "我公司拥有大量成功案例，并百分之百保证项目验收。"
    )

    assert any(item.severity == "blocking" for item in findings)


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
