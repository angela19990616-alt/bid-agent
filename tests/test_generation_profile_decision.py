from io import BytesIO
from uuid import uuid4

from docx import Document

from app.agents.proposal_planner import ProposalPlanner
from app.rules.engine import RuleEngine
from app.services.generation_profile_service import GenerationProfileService
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
