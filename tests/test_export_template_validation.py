import pytest
from types import SimpleNamespace

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
    monkeypatch.setattr(
        "app.services.export_service.GenerationProfileService.get",
        lambda _self, _project_id: type(
            "Profile",
            (),
            {"generation_mode": "planned"},
        )(),
    )
    monkeypatch.setattr(ExportService, "_load_full_export_input", load)

    with pytest.raises(ExportValidationError, match="交付审查未通过"):
        ExportService().create_full("project")

    assert loaded is False


def test_field_only_template_skips_proposal_review_and_allows_empty_sections(
    monkeypatch,
):
    calls = {"review": 0, "allow_empty": False}

    monkeypatch.setattr(
        "app.services.export_service.GenerationProfileService.get",
        lambda _self, _project_id: type(
            "Profile",
            (),
            {"generation_mode": "strict_template"},
        )(),
    )
    monkeypatch.setattr(
        "app.services.export_service.SectionService.list",
        lambda _self, _project_id: [],
    )

    class Review:
        def prepare_for_export(self, _project_id):
            calls["review"] += 1
            return {"overall": {"recommended_for_delivery": False}}

    def load(_self, _project_id, *, allow_empty_sections=False):
        calls["allow_empty"] = allow_empty_sections
        raise RuntimeError("stop after checking field-only dispatch")

    monkeypatch.setattr(
        "app.services.export_service.ProposalReviewService",
        Review,
    )
    monkeypatch.setattr(ExportService, "_load_full_export_input", load)

    with pytest.raises(RuntimeError, match="field-only dispatch"):
        ExportService().create_full("project")

    assert calls == {"review": 0, "allow_empty": True}


def test_template_preview_builds_real_docx_without_delivery_record(
    monkeypatch, tmp_path,
):
    template = tmp_path / "template.docx"
    template.write_bytes(b"template-package")
    captured = {}

    class ProfileService:
        def get(self, _project_id):
            return SimpleNamespace(
                generation_mode="strict_template",
                template_descriptor={},
            )

        def template_path(self, _profile):
            return template

        def template_field_decisions(self, *_args):
            return [{
                "field_key": "bidder_name",
                "value": "候选企业名称",
                "status": "REVIEW_REQUIRED",
            }]

    class TemplateService:
        def fill_docx(self, **kwargs):
            captured.update(kwargs)
            kwargs["output_path"].write_bytes(b"preview-docx")

    monkeypatch.setattr(
        "app.services.export_service.GenerationProfileService",
        ProfileService,
    )
    monkeypatch.setattr(
        "app.services.export_service.ResponseTemplateService",
        TemplateService,
    )
    monkeypatch.setattr(
        "app.services.export_service.EnterpriseFactResolver.resolve",
        lambda _self, _project_id: [],
    )
    monkeypatch.setattr(
        "app.services.export_service.CaseFactResolver.resolve",
        lambda _self, _project_id: {},
    )
    monkeypatch.setattr(
        "app.services.export_service.EntityResolutionService.resolve_project",
        lambda _self, _project_id: None,
    )
    monkeypatch.setattr(
        ExportService,
        "_load_full_export_input",
        lambda _self, _project_id, **_kwargs: {
            "project_name": "测试项目",
            "sections": [],
        },
    )
    monkeypatch.setattr(
        ExportService,
        "resolve_path",
        staticmethod(lambda _storage_key: tmp_path / "preview.docx"),
    )

    path = ExportService().create_template_preview("project")

    assert path.read_bytes() == b"preview-docx"
    assert captured["template_content"] == b"template-package"
    assert captured["field_values"] == {
        "bidder_name": "候选企业名称",
    }
    assert captured["document_title"] == "《AI投标文件+测试项目》"
