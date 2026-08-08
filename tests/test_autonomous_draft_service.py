from uuid import uuid4

from app.services.autonomous_draft_service import AutonomousDraftService


def test_autonomous_draft_generates_missing_sections_and_reviews(monkeypatch):
    project_id = uuid4()
    job_id = uuid4()
    existing_id = uuid4()
    missing_id = uuid4()
    generated = []
    progress = []

    monkeypatch.setattr(
        "app.services.autonomous_draft_service.SectionService.list",
        lambda _self, _project_id: [
            {
                "id": existing_id,
                "title": "项目理解",
                "current_version": {"content": "已有内容"},
            },
            {
                "id": missing_id,
                "title": "实施计划",
                "current_version": None,
            },
        ],
    )
    monkeypatch.setattr(
        "app.services.autonomous_draft_service.SectionService.generate",
        lambda _self, project, section: generated.append((project, section)),
    )
    monkeypatch.setattr(
        "app.services.autonomous_draft_service.ConflictService.assert_section_unblocked",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        "app.services.autonomous_draft_service.ProposalReviewService.prepare_for_export",
        lambda _self, _project_id: {
            "overall": {"recommended_for_delivery": False}
        },
    )
    monkeypatch.setattr(
        "app.services.autonomous_draft_service.WorkspaceJobService.update_progress",
        lambda job, value: progress.append((job, value)),
    )

    result = AutonomousDraftService().run(project_id, job_id)

    assert generated == [(project_id, missing_id)]
    assert result["generated_count"] == 2
    assert result["recommended_for_delivery"] is False
    assert progress[-1] == (job_id, 95)
