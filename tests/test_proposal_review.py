from uuid import uuid4

from app.knowledge.engine import KnowledgeMatch
from app.rules.engine import RuleEngine
from app.services.proposal_review_service import (
    ProposalReviewService,
    UUID_PATTERN,
)
from app.services.provenance_service import ProvenanceService
from app.workflows.controlled_pipeline import STAGES


def requirement(
    *,
    key="R0001",
    kind="technical",
    text="制定项目实施计划，明确主要工作、进度安排和阶段成果",
):
    return {
        "public_key": key,
        "type": kind,
        "title": text,
        "normalized_text": text,
        "quote": text,
        "source_location": "采购文件，第 12 页",
    }


def trace(
    *,
    paragraph_index=0,
    source_type="requirement",
    status="verified",
    title="实施计划要求",
):
    return {
        "paragraph_index": paragraph_index,
        "source_type": source_type,
        "source_title": title,
        "source_location": "采购文件，第 12 页",
        "usage_description": "响应采购要求",
        "verification_status": status,
        "confidence": 0.95,
    }


def proposal(
    content="围绕项目实施计划，明确主要工作、进度安排和阶段成果。",
    *,
    requirements=None,
    traces=None,
):
    items = requirements or [requirement()]
    return {
        "project_name": "测试项目",
        "requirements": items,
        "sections": [
            {
                "section_id": uuid4(),
                "title": "实施计划与进度安排",
                "content": content,
                "requirement_public_keys": [
                    item["public_key"] for item in items
                ],
                "provenance": traces if traces is not None else [trace()],
            }
        ],
    }


def final_review(data):
    return ProposalReviewService.review(
        data,
        RuleEngine().load_default("compliance"),
        phase="final",
    )


def test_final_review_blocks_requirement_uuid_and_hides_it_from_report():
    leaked = str(uuid4())
    report = final_review(proposal(f"实施计划内部编号 {leaked}"))

    assert report["overall"]["internal_identifier_leak_count"] == 1
    assert report["overall"]["recommended_for_delivery"] is False
    assert leaked not in str(report)


def test_final_review_blocks_internal_database_fields():
    report = final_review(
        proposal("实施计划使用 requirement_id 和 source_chunk_id 调试。")
    )

    assert any(
        item["risk_description"] == "内部系统字段泄露"
        for item in report["truth_and_privacy_review"]
    )


def test_unverified_enterprise_facts_cannot_enter_final_document():
    content = "我公司成立于2001年，已完成项目数量超过300个。"
    provenance = [
        trace(source_type="model_inference", status="unverified")
    ]
    report = final_review(proposal(content, traces=provenance))
    fixed = ProposalReviewService.auto_fix(
        content,
        provenance,
        RuleEngine().load_default("compliance"),
    )

    assert report["overall"]["has_blocking_risk"] is True
    assert "成立于" not in fixed
    assert "项目数量" not in fixed


def test_historical_case_content_creates_usage_trace():
    knowledge_id = uuid4()
    match = KnowledgeMatch(
        knowledge_id=knowledge_id,
        category="historical_bid",
        title="历史项目实施方案",
        content="实施计划包括主要工作、进度安排、阶段成果和质量检查。",
        score=0.88,
        rationale="术语匹配",
        metadata={"verified_enterprise_fact": False},
    )
    records, usage = ProvenanceService.build(
        section_title="实施计划与进度安排",
        content="实施计划包括主要工作、进度安排、阶段成果和质量检查。",
        requirements=[],
        matches=[match],
    )

    assert any(item.source_type == "historical_case" for item in records)
    assert usage[0]["case_title"] == "历史项目实施方案"
    assert usage[0]["allowed_in_final"] is True


def test_every_unmatched_paragraph_is_marked_model_inference():
    records, _ = ProvenanceService.build(
        section_title="实施计划",
        content="提出一种补充性工作思路。",
        requirements=[],
        matches=[],
    )

    assert records[0].source_type == "model_inference"
    assert records[0].verification_status == "unverified"


def test_unverified_high_risk_model_inference_is_removed():
    content = "由质量总监组织三级联审，并在48小时内完成。"
    fixed = ProposalReviewService.auto_fix(
        content,
        [trace(source_type="model_inference", status="unverified")],
    )

    assert fixed == ""


def test_complete_chapter_does_not_bypass_traceability_gate():
    report = final_review(proposal(traces=[]))

    assert report["deliverability_gate"]["checks"][
        "traceability_threshold"
    ] is False
    assert report["overall"]["recommended_for_delivery"] is False


def test_blocking_truth_risk_marks_review_not_recommended():
    report = final_review(
        proposal(
            "财政部《地方政府专项债券项目审核标准指引》要求本项目执行三级联审。",
            traces=[trace(source_type="model_inference", status="unverified")],
        )
    )

    assert report["overall"]["has_blocking_risk"] is True
    assert report["overall"]["recommended_for_delivery"] is False


def test_uncovered_scoring_item_is_reported():
    scoring = requirement(
        key="R0002",
        kind="scoring",
        text="实施方案完整性和可行性，满分10分",
    )
    data = proposal(requirements=[requirement(), scoring])
    data["sections"][0]["requirement_public_keys"] = ["R0001"]
    report = final_review(data)

    assert report["scoring_coverage"][0]["coverage_status"] == "not_covered"
    assert report["overall"]["scoring_coverage_rate"] == 0


def test_review_never_exposes_internal_uuid():
    report = final_review(proposal())

    assert UUID_PATTERN.search(str(report)) is None
    assert "section_id" not in str(report)


def test_auto_fix_removes_markdown_emoji_and_debug_information():
    content = "# 计划\n✅ **严格确保**按期完成\nrequirement_id=debug"
    fixed = ProposalReviewService.auto_fix(content, [])

    assert "#" not in fixed
    assert "✅" not in fixed
    assert "**" not in fixed
    assert "requirement_id" not in fixed
    assert "严格确保" not in fixed


def test_review_auto_fix_and_final_review_are_explicit_workflow_stages():
    assert (
        STAGES.index("proposal_review")
        < STAGES.index("auto_fix")
        < STAGES.index("final_review")
        < STAGES.index("deliverability_gate")
        < STAGES.index("export")
    )


def test_regression_sample_unverified_specifics_are_detected():
    phrases = [
        "国家发改委《地方政府专项债券项目资金绩效管理办法》",
        "财政部《地方政府专项债券项目审核标准指引》",
        "四川省最新申报口径",
        "省发改委",
        "3个工作日",
        "48小时",
        "第150日历天",
        "三级联审",
        "质量总监",
        "会计师事务所",
        "律师事务所",
        "合同第九章第四条第3款",
        "纸质文档一式4份",
        "PDF含目录书签",
    ]
    content = "\n".join(phrases)
    report = final_review(
        proposal(
            content,
            traces=[
                trace(
                    paragraph_index=index,
                    source_type="model_inference",
                    status="unverified",
                )
                for index in range(len(phrases))
            ],
        )
    )
    descriptions = " ".join(
        item["risk_description"]
        for item in report["truth_and_privacy_review"]
    )

    for phrase in phrases:
        assert phrase in descriptions


def test_delivery_gate_requires_final_recheck():
    initial = ProposalReviewService.review(
        proposal(),
        RuleEngine().load_default("compliance"),
        phase="initial",
    )

    assert initial["deliverability_gate"]["checks"][
        "auto_fix_recheck_completed"
    ] is False
    assert initial["overall"]["recommended_for_delivery"] is False
