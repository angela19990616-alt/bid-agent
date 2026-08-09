from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document

from app.agents.proposal_planner import ProposalPlanner
from app.rules.engine import RuleEngine
from app.services.generation_profile_service import GenerationProfileService
from app.services.generation_profile_service import GenerationProfile
from app.services.response_template_service import ResponseTemplateService


def _docx(*paragraphs: str) -> bytes:
    document = Document()
    for value in paragraphs:
        document.add_paragraph(value)
    stream = BytesIO()
    document.save(stream)
    return stream.getvalue()


def test_no_template_falls_back_to_requirement_driven_planning():
    descriptor = ResponseTemplateService().detect(
        "采购文件.docx",
        _docx("采购需求", "供应商应制定实施计划与进度安排。"),
    )
    mode = GenerationProfileService.mode_for_descriptor(
        descriptor.snapshot()
    )
    requirement_id = uuid4()
    outline = ProposalPlanner().plan(
        [{
            "id": requirement_id,
            "proposal_chapter": "实施计划与进度安排",
            "need_generation": True,
        }],
        RuleEngine().load_default("writing"),
    )

    assert descriptor.detected is False
    assert mode == "planned"
    assert outline[0].title == "实施计划与进度安排"
    assert outline[0].requirement_ids == (requirement_id,)


def test_docx_and_pdf_templates_have_explicit_modes():
    service = GenerationProfileService

    assert service.mode_for_descriptor({
        "detected": True, "source_format": "docx"
    }) == "strict_template"
    assert service.mode_for_descriptor({
        "detected": True, "source_format": "pdf"
    }) == "pdf_template_manual_fill"
    assert service.writer_strategy_for_mode("strict_template") == (
        "strict_template_writer"
    )
    assert service.writer_strategy_for_mode("planned") == (
        "planned_proposal_writer"
    )
    assert service.writer_strategy_for_mode(
        "template_conversion_required"
    ) is None


def test_attachment_template_priority_cannot_be_downgraded():
    preferred = GenerationProfileService.preferred_mode

    assert preferred("planned", "pdf_template_manual_fill") == (
        "pdf_template_manual_fill"
    )
    assert preferred("pdf_template_manual_fill", "planned") == (
        "pdf_template_manual_fill"
    )
    assert preferred("pdf_template_manual_fill", "strict_template") == (
        "strict_template"
    )
    assert preferred("strict_template", "planned") == "strict_template"
    assert preferred("template_conversion_required", "planned") == (
        "template_conversion_required"
    )


def test_template_field_decisions_separate_tender_and_enterprise_facts():
    profile = GenerationProfile(
        project_id=uuid4(),
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={
            "field_labels": ["项目编号", "供应商名称", "法定代表人"]
        },
        template_field_values={
            "project_number": "SCXHR20250320",
            "bidder_name": "北京大岳咨询有限责任公司",
        },
        template_filename="自贡招标文件.docx",
        last_fill_report={},
    )

    decisions = {
        item["field_key"]: item
        for item in GenerationProfileService.template_field_decisions(profile)
    }

    assert decisions["project_number"]["status"] == "AUTO_FILL"
    assert decisions["project_number"]["source_type"] == "tender_document"
    assert decisions["project_number"]["expected_value_type_label"] == "项目编号"
    assert decisions["project_number"]["type_validation"] == "passed"
    assert decisions["bidder_name"]["status"] == "MISSING"
    assert "绑定当前投标主体" in decisions["bidder_name"]["reason"]
    assert decisions["legal_representative"]["status"] == "MISSING"
    assert decisions["legal_representative"]["expected_value_type_label"] == "姓名"
    assert decisions["legal_representative"]["type_validation"] == "missing"


def test_confirmed_manual_organization_value_cannot_bypass_entity_binding():
    profile = GenerationProfile(
        project_id=uuid4(),
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={"field_labels": ["供应商名称"]},
        template_field_values={"bidder_name": "北京大岳咨询有限责任公司"},
        last_fill_report={
            "field_reviews": {
                "bidder_name": {
                    "status": "confirmed",
                    "value": "北京大岳咨询有限责任公司",
                }
            }
        },
    )

    decision = GenerationProfileService.template_field_decisions(profile)[0]

    assert decision["status"] == "MISSING"
    assert decision["binding_status"] == "binding_required"


def test_confirmed_case_organization_value_cannot_become_enterprise_fact():
    profile = GenerationProfile(
        project_id=uuid4(),
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={"field_labels": ["供应商名称"]},
        template_field_values={"bidder_name": "北京大岳咨询有限责任公司"},
        last_fill_report={
            "field_reviews": {
                "bidder_name": {
                    "status": "confirmed",
                    "value": "北京大岳咨询有限责任公司",
                    "source_reference": "自贡项目中标投标文件.docx",
                    "evidence_title": "自贡项目中标投标文件.docx",
                    "evidence_excerpt": "供应商名称：北京大岳咨询有限责任公司",
                    "evidence_location": "机构私有案例库",
                    "evidence_match_count": 3,
                }
            }
        },
    )

    decision = GenerationProfileService.template_field_decisions(profile)[0]

    assert decision["status"] == "MISSING"
    assert decision["value"] is None
    assert "投标主体" in decision["reason"]


def test_bulk_field_update_cannot_bypass_semantic_type_validation():
    with pytest.raises(ValueError, match="字段类型（姓名）"):
        GenerationProfileService.update_template_fields(
            uuid4(), {"legal_representative": "法人或授权代表"}
        )


def test_case_candidate_cannot_select_a_person_phone_without_role_binding():
    from app.knowledge.case_fact_resolver import CaseFactCandidate

    profile = GenerationProfile(
        project_id=uuid4(),
        generation_mode="strict_template",
        historical_case_mode="closest_case",
        template_descriptor={"field_labels": ["联系电话"]},
        template_field_values={},
        last_fill_report={},
    )
    candidate = CaseFactCandidate(
        canonical_key="contact_phone",
        value="010-12345678",
        source_title="案例一·中标响应文件",
        source_excerpt="联系电话：010-12345678",
        source_location="第 10 段",
        confidence=0.8,
        match_count=3,
        alternatives=("13800138000",),
    )

    decision = GenerationProfileService.template_field_decisions(
        profile, case_candidates={"contact_phone": candidate}
    )[0]

    assert decision["status"] == "MISSING"
    assert decision["value"] is None
    assert "角色绑定" in decision["reason"]
