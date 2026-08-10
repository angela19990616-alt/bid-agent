from types import SimpleNamespace
from uuid import uuid4

from app.services.bid_readiness_service import BidReadinessService


RULES = {
    "material_scoring_markers": ["业绩"],
    "criterion_types": {
        "business_case": ["业绩"],
        "person_certificate": ["证书"],
        "organization_qualification": ["企业资质"],
    },
    "selection_buffers": {
        "business_case": 2,
        "person_certificate": 1,
        "organization_qualification": 1,
        "maximum_extra": 3,
    },
    "constraint_groups": {},
    "approval_policy": {"full_contract_markers": ["合同全页"]},
}


def build(service, *, requirements=None, qualification=None):
    return service.build(
        project_id=uuid4(),
        profile=SimpleNamespace(
            generation_mode="planned",
            template_descriptor={},
        ),
        sections=[{"title": "技术方案", "sort_order": 1}],
        requirements=requirements or [],
        knowledge=[],
        format_requirements=[],
        qualification_responses=qualification or [],
        rules=RULES,
    )


def test_outline_confirmation_is_required_before_writing():
    decisions = {}
    service = BidReadinessService(decision_loader=lambda _project_id: decisions)

    result = build(service)

    assert result["writing_gate"]["ready"] is False
    outline = result["outline_gate"]
    decisions[outline["review_key"]] = {
        "content_hash": outline["content_hash"],
        "status": "confirmed",
    }

    confirmed = build(service)

    assert confirmed["writing_gate"]["ready"] is True


def test_changed_outline_invalidates_old_confirmation():
    decisions = {}
    service = BidReadinessService(decision_loader=lambda _project_id: decisions)
    first = build(service)
    decisions["outline:structure"] = {
        "content_hash": first["outline_gate"]["content_hash"],
        "status": "confirmed",
    }
    changed = service.build(
        project_id=uuid4(),
        profile=SimpleNamespace(
            generation_mode="planned",
            template_descriptor={},
        ),
        sections=[{"title": "变更后的目录", "sort_order": 1}],
        requirements=[],
        knowledge=[],
        format_requirements=[],
        qualification_responses=[],
        rules=RULES,
    )

    assert changed["outline_gate"]["status"] == "pending"
    assert changed["writing_gate"]["ready"] is False


def test_commercial_deviation_requires_explicit_review():
    service = BidReadinessService(decision_loader=lambda _project_id: {})
    requirement = {
        "id": uuid4(),
        "title": "商务条款偏离表",
        "normalized_text": "商务条款偏离表原则上填写无偏离",
        "quote": "商务条款偏离表",
        "scoring_impact": "no_score",
        "sources": [],
    }

    result = build(service, requirements=[requirement])

    deviation = result["commercial_deviations"][0]
    assert deviation["status"] == "pending"
    assert "待审核" in "；".join(result["delivery_gate"]["blockers"])


def test_missing_verified_qualification_material_blocks_delivery():
    service = BidReadinessService(decision_loader=lambda _project_id: {})
    result = build(
        service,
        qualification=[{
            "requirement_id": str(uuid4()),
            "requirement": "提供人员证书扫描件",
            "status": "manual_material_required",
            "matches": [],
        }],
    )

    material = next(
        item for item in result["review_items"]
        if item["category"] == "qualification_material"
    )
    assert material["confirmable"] is False
    assert "尚未找到" in material["blocker"]


def test_same_kind_scoring_items_share_one_human_review_group():
    service = BidReadinessService(decision_loader=lambda _project_id: {})
    requirements = [
        {
            "id": uuid4(),
            "title": f"企业业绩评分{i}",
            "normalized_text": "企业业绩每项加1分，最高得2分",
            "quote": "企业业绩每项加1分，最高得2分",
            "scoring_impact": "score_item",
            "sources": [],
        }
        for i in range(2)
    ]

    result = build(service, requirements=requirements)
    evidence_reviews = [
        item for item in result["review_items"]
        if item["category"] == "scoring_evidence"
    ]

    assert len(result["scoring_evidence_plans"]) == 2
    assert len(evidence_reviews) == 1
    assert "2 个评分事项" in evidence_reviews[0]["title"]


def test_strict_template_always_requires_format_fidelity_review():
    service = BidReadinessService(decision_loader=lambda _project_id: {})
    result = service.build(
        project_id=uuid4(),
        profile=SimpleNamespace(
            generation_mode="strict_template",
            template_descriptor={
                "outline": [{"title": "投标函", "level": 1}],
                "table_count": 3,
                "fonts": ["宋体"],
            },
        ),
        sections=[],
        requirements=[],
        knowledge=[],
        format_requirements=[],
        qualification_responses=[],
        rules=RULES,
    )

    fidelity = next(
        item for item in result["review_items"]
        if item["review_key"] == "format:template-fidelity"
    )
    assert fidelity["status"] == "pending"
    assert result["outline_gate"]["confirmable"] is True
    assert result["delivery_gate"]["ready"] is False


def test_field_only_strict_template_does_not_require_generated_outline():
    service = BidReadinessService(decision_loader=lambda _project_id: {})

    result = service.build(
        project_id=uuid4(),
        profile=SimpleNamespace(
            generation_mode="strict_template",
            template_descriptor={"table_count": 2, "field_count": 8},
        ),
        sections=[],
        requirements=[],
        knowledge=[],
        format_requirements=[],
        qualification_responses=[],
        rules=RULES,
    )

    assert result["outline_gate"]["confirmable"] is True
    assert result["outline_gate"]["blocker"] is None
