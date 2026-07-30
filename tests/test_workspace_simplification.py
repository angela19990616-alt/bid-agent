from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import app.services.workspace_service as workspace_module
from app.services.workspace_service import WorkspaceService


class FakeRequirementService:
    def __init__(self):
        self.calls = 0

    def list(self, _workspace_id):
        self.calls += 1
        return [
            {"id": uuid4(), "need_generation": True},
            {"id": uuid4(), "need_generation": False},
        ]


def test_workspace_summary_loads_requirements_once(monkeypatch):
    workspace_id = uuid4()
    requirements = FakeRequirementService()
    service = WorkspaceService(
        document_service=SimpleNamespace(
            list=lambda _workspace_id: [
                SimpleNamespace(source_count=20)
            ]
        ),
        requirement_service=requirements,
        plan_service=SimpleNamespace(),
    )
    workspace = SimpleNamespace(
        id=workspace_id,
        name="测试招标文件",
        status="outline_ready",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        workspace_module.ProjectService,
        "get",
        lambda _service, _workspace_id: workspace,
    )
    monkeypatch.setattr(
        workspace_module,
        "SectionService",
        lambda: SimpleNamespace(list=lambda _workspace_id: []),
    )
    monkeypatch.setattr(
        workspace_module.ProcessingEtaService,
        "estimate",
        lambda *_args, **_kwargs: SimpleNamespace(
            remaining_seconds_low=0,
            remaining_seconds_high=0,
            sample_count=1,
            basis="completed",
        ),
    )
    monkeypatch.setattr(
        workspace_module.ModelBudgetService,
        "summary_for_project",
        lambda _workspace_id: {},
    )
    monkeypatch.setattr(
        workspace_module.WorkspaceJobService,
        "latest_status",
        lambda _workspace_id: None,
    )

    result = service.get(workspace_id)

    assert requirements.calls == 1
    assert len(result["technical_requirements"]) == 1
    assert result["compliance_reminder_count"] == 1
