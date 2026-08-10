from uuid import uuid4

from app.core.scoring_evidence import ScoringEvidencePlanner


RULES = {
    "material_scoring_markers": ["业绩", "合同", "证书", "项目组成员"],
    "criterion_types": {
        "business_case": ["业绩", "合同", "案例"],
        "person_certificate": ["项目组成员", "证书", "咨询工程师"],
        "organization_qualification": ["企业资质"],
    },
    "selection_buffers": {
        "business_case": 2,
        "person_certificate": 1,
        "organization_qualification": 1,
        "maximum_extra": 3,
    },
    "constraint_groups": {
        "government_client": ["政府方"],
        "ppp_service": ["PPP", "履约管理", "绩效评价"],
        "certificate_types": ["咨询工程师"],
        "employment_relation": ["社保", "投标单位"],
        "one_person_one_score": ["一人多证", "按1分计"],
    },
    "approval_policy": {
        "full_contract_markers": ["合同全页"],
    },
}


def scoring_requirement(text):
    return {
        "id": uuid4(),
        "title": "评分材料",
        "normalized_text": text,
        "quote": text,
        "scoring_impact": "score_item",
        "sources": [],
    }


def enterprise_fact(title, category, **metadata):
    defaults = {
        "verified_enterprise_fact": True,
        "asset_reference": "private://evidence/file",
        "evidence_location": "第 2 页 · 证明材料",
    }
    defaults.update(metadata)
    return {
        "title": title,
        "content": title,
        "category": category,
        "metadata": defaults,
    }


def test_business_case_plan_calculates_full_score_and_buffer():
    requirement = scoring_requirement(
        "作为政府方PPP履约管理顾问的业绩，每项加2分，最高得12分。"
    )
    knowledge = [
        enterprise_fact(
            f"政府方PPP履约管理项目{i}",
            "case_study",
            contract_number=f"HT-{i}",
            client_type="government",
        )
        for i in range(8)
    ]

    plan = ScoringEvidencePlanner.plan(
        [requirement], knowledge, RULES
    )[0]

    assert plan["criterion_type"] == "business_case"
    assert plan["minimum_count"] == 6
    assert plan["recommended_count"] == 8
    assert plan["selected_count"] == 8
    assert plan["readiness"] == "ready_for_review"


def test_historical_bid_is_never_used_as_enterprise_evidence():
    requirement = scoring_requirement("类似项目业绩，每项加2分，最高得4分。")
    knowledge = [
        enterprise_fact("历史中标文件中的案例", "historical_bid"),
    ]

    plan = ScoringEvidencePlanner.plan(
        [requirement], knowledge, RULES
    )[0]

    assert plan["selected_candidates"] == []
    assert plan["readiness"] == "verified_material_insufficient"


def test_string_false_is_not_treated_as_verified_enterprise_fact():
    requirement = scoring_requirement("类似项目业绩，每项加1分，最高得1分。")
    knowledge = [
        enterprise_fact(
            "尚未核验的项目材料",
            "case_study",
            contract_number="HT-1",
            verified_enterprise_fact="false",
        )
    ]

    plan = ScoringEvidencePlanner.plan(
        [requirement], knowledge, RULES
    )[0]

    assert plan["selected_candidates"] == []
    assert plan["readiness"] == "verified_material_insufficient"


def test_person_certificates_are_deduplicated_by_holder():
    requirement = scoring_requirement(
        "项目组成员持咨询工程师证书，每个证书加1分，最高得2分，"
        "一人多证按1分计，须核验投标单位社保。"
    )
    knowledge = [
        enterprise_fact(
            "张三咨询工程师证书A",
            "qualification",
            holder="张三",
            employment_verified=True,
        ),
        enterprise_fact(
            "张三咨询工程师证书B",
            "qualification",
            holder="张三",
            employment_verified=True,
        ),
        enterprise_fact(
            "李四咨询工程师证书",
            "qualification",
            holder="李四",
            employment_verified=True,
        ),
    ]

    plan = ScoringEvidencePlanner.plan(
        [requirement], knowledge, RULES
    )[0]

    assert plan["minimum_count"] == 2
    assert plan["candidate_count"] == 2
    assert {item["holder"] for item in plan["selected_candidates"]} == {
        "张三", "李四"
    }


def test_full_contract_requires_business_approval():
    requirement = scoring_requirement("类似项目合同业绩，每项加1分，最高得1分。")
    knowledge = [
        enterprise_fact(
            "项目合同全页",
            "case_study",
            contract_number="HT-1",
            document_scope="full_contract",
            approval_status="pending",
        )
    ]

    plan = ScoringEvidencePlanner.plan(
        [requirement], knowledge, RULES
    )[0]

    assert plan["readiness"] == "approval_required"
    assert plan["selected_candidates"][0]["approval_status"] == "required"
