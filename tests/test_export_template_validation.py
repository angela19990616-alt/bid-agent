import pytest

from app.services.export_service import ExportService, ExportValidationError
from app.services.response_template_service import TemplateFillReport


def test_unresolved_enterprise_fields_do_not_block_draft_export():
    report = TemplateFillReport(
        filled_fields=("project_name", "project_number"),
        unresolved_fields=("bidder_name",),
        inserted_sections=("技术方案",),
        unresolved_sections=(),
    )

    ExportService._validate_template_fill(report)


def test_unresolved_section_anchor_still_blocks_template_export():
    report = TemplateFillReport(
        filled_fields=("project_name",),
        unresolved_fields=(),
        inserted_sections=(),
        unresolved_sections=("实施计划",),
    )

    with pytest.raises(ExportValidationError, match="实施计划"):
        ExportService._validate_template_fill(report)


def test_formal_export_is_blocked_when_delivery_review_fails(monkeypatch):
    loaded = False

    class Review:
        def prepare_for_export(self, _project_id):
            return {"overall": {"recommended_for_delivery": False}}

    def load(_self, _project_id):
        nonlocal loaded
        loaded = True
        return {}

    monkeypatch.setattr(
        "app.services.export_service.ProposalReviewService",
        Review,
    )
    monkeypatch.setattr(ExportService, "_load_full_export_input", load)

    with pytest.raises(ExportValidationError, match="交付审查未通过"):
        ExportService().create_full("project")

    assert loaded is False
