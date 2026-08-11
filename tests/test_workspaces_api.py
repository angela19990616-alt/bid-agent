from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

import app.api.workspaces as workspace_api
from app.api.workspaces import (
    get_workspace_access_service,
    get_workspace_job_service,
    get_workspace_service,
)
from app.main import app
from app.models.requirements import RequirementStrategyUpdate
from app.models.generation_profiles import (
    OrganizationBindingUpdate,
    TemplateFieldReviewUpdate,
    TemplateFieldsUpdate,
    TemplateVariableReviewUpdate,
)
from app.services.workspace_service import InvalidTenderDocumentError
from app.services.workspace_access_service import (
    SessionAccess,
    WorkspaceAccessDeniedError,
)


NOW = datetime.now(UTC)


class FakeWorkspaceService:
    def __init__(self):
        self.id = uuid4()

    def create_from_upload(self, filename, content_type, content):
        return {
            "id": self.id,
            "name": "智慧项目招标文件",
            "status": "outline_ready",
            "created_at": NOW,
            "updated_at": NOW,
            "document": {
                "id": uuid4(),
                "project_id": self.id,
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(content),
                "status": "parsed",
                "source_count": 12,
                "validation_status": "valid",
                "validation_score": 0.91,
                "knowledge_status": "eligible",
                "knowledge_scope": "organization_private",
                "created_at": NOW,
                "updated_at": NOW,
            },
            "technical_requirements": [],
            "compliance_reminder_count": 4,
            "outline": [],
        }

    def get(self, workspace_id):
        return self.create_from_upload(
            "招标文件.pdf", "application/pdf", b"pdf"
        )

class FakeAccessService:
    def __init__(self):
        self.bound = None

    def session(self, request):
        return SessionAccess("s" * 43, "127.0.0.1", True)

    def bind(self, workspace_id, access):
        self.bound = (workspace_id, access)

    def authorize(self, workspace_id, request):
        return None


class FakeJobService:
    def __init__(self):
        self.enqueued = None

    def enqueue(self, workspace_id, document_id, run_id):
        self.enqueued = (workspace_id, document_id, run_id)
        return uuid4()


job_service = FakeJobService()


def setup_function():
    global job_service
    job_service = FakeJobService()
    app.dependency_overrides[get_workspace_access_service] = (
        lambda: FakeAccessService()
    )
    app.dependency_overrides[get_workspace_job_service] = (
        lambda: job_service
    )


def teardown_function():
    app.dependency_overrides.clear()


def test_response_views_filter_by_strategy_dimensions(monkeypatch):
    items = [
        {
            "id": "proposal",
            "response_action": "write_into_proposal",
            "scoring_impact": "no_score",
            "type": "technical_requirement",
        },
        {
            "id": "score",
            "response_action": "write_into_proposal",
            "scoring_impact": "score_item",
            "type": "scoring_requirement",
        },
        {
            "id": "risk",
            "response_action": "risk_notice",
            "scoring_impact": "penalty_risk",
            "type": "format_requirement",
        },
    ]
    monkeypatch.setattr(
        workspace_api,
        "RequirementService",
        lambda: SimpleNamespace(list=lambda _workspace_id: items),
    )
    workspace_id = uuid4()

    assert {
        item["id"] for item in workspace_api.list_workspace_requirements(
            workspace_id, "proposal", None
        )
    } == {"proposal", "score"}
    assert [
        item["id"] for item in workspace_api.list_workspace_requirements(
            workspace_id, "scoring", None
        )
    ] == ["score"]
    assert [
        item["id"] for item in workspace_api.list_workspace_requirements(
            workspace_id, "risk", None
        )
    ] == ["risk"]


def test_verified_template_fields_are_saved_through_workspace_flow(monkeypatch):
    workspace_id = uuid4()
    calls = {}
    service = FakeWorkspaceService()
    monkeypatch.setattr(
        workspace_api,
        "GenerationProfileService",
        SimpleNamespace(
            update_template_fields=lambda item_id, values: calls.update(
                workspace_id=item_id,
                values=values,
            )
        ),
    )

    result = workspace_api.update_workspace_template_fields(
        workspace_id,
        TemplateFieldsUpdate(
            values={"bidder_name": "已核验供应商"}
        ),
        None,
        service,
    )

    assert calls == {
        "workspace_id": workspace_id,
        "values": {"bidder_name": "已核验供应商"},
    }
    assert result["id"] == service.id


def test_manual_template_field_edit_is_confirmed_through_workspace_flow(
    monkeypatch,
):
    workspace_id = uuid4()
    calls = {}
    service = FakeWorkspaceService()
    monkeypatch.setattr(
        workspace_api,
        "GenerationProfileService",
        SimpleNamespace(
            review_template_field=lambda item_id, key, action, value=None: (
                calls.update(
                    workspace_id=item_id,
                    field_key=key,
                    action=action,
                    value=value,
                )
            )
        ),
    )

    result = workspace_api.review_workspace_template_field(
        workspace_id,
        TemplateFieldReviewUpdate(
            field_key="bidder_name",
            action="confirm",
            value="人工核验后的供应商名称",
        ),
        None,
        service,
    )

    assert calls == {
        "workspace_id": workspace_id,
        "field_key": "bidder_name",
        "action": "confirm",
        "value": "人工核验后的供应商名称",
    }
    assert result["id"] == service.id


def test_business_variable_is_reviewed_once_through_workspace_flow(
    monkeypatch,
):
    workspace_id = uuid4()
    calls = {}
    service = FakeWorkspaceService()
    monkeypatch.setattr(
        workspace_api,
        "GenerationProfileService",
        SimpleNamespace(
            review_template_variable=(
                lambda item_id, key, action, value=None, candidate_key=None: calls.update(
                    workspace_id=item_id,
                    variable_key=key,
                    action=action,
                    value=value,
                    candidate_key=candidate_key,
                )
            )
        ),
    )

    result = workspace_api.review_workspace_template_variable(
        workspace_id,
        TemplateVariableReviewUpdate(
            variable_key="organization.legal_representative.name",
            action="confirm",
            candidate_key="1234567890abcdef",
        ),
        None,
        service,
    )

    assert calls == {
        "workspace_id": workspace_id,
        "variable_key": "organization.legal_representative.name",
        "action": "confirm",
        "value": None,
        "candidate_key": "1234567890abcdef",
    }
    assert result["id"] == service.id


def test_verified_organization_candidate_can_be_bound(monkeypatch):
    workspace_id = uuid4()
    organization_id = uuid4()
    calls = {}
    service = FakeWorkspaceService()
    resolver = SimpleNamespace(
        bind_organization=lambda item_id, organization_id: calls.update(
            workspace_id=item_id,
            organization_id=organization_id,
        )
    )
    monkeypatch.setattr(
        workspace_api,
        "EntityResolutionService",
        lambda: resolver,
    )

    result = workspace_api.bind_workspace_organization(
        workspace_id,
        OrganizationBindingUpdate(organization_id=organization_id),
        None,
        service,
    )

    assert calls == {
        "workspace_id": workspace_id,
        "organization_id": organization_id,
    }
    assert result["id"] == service.id


def test_manual_strategy_switch_reconciles_draft_outline(monkeypatch):
    calls = {}
    requirement_id = uuid4()
    workspace_id = uuid4()
    updated = {"id": requirement_id}
    monkeypatch.setattr(
        workspace_api,
        "RequirementService",
        lambda: SimpleNamespace(
            update_response_strategy=lambda project_id, item_id, target: (
                calls.update(
                    strategy=(project_id, item_id, target)
                )
                or updated
            )
        ),
    )
    monkeypatch.setattr(
        workspace_api,
        "ProposalPlanService",
        lambda: SimpleNamespace(
            reconcile_requirement_feedback=lambda project_id, item_id: (
                calls.update(outline=(project_id, item_id))
            )
        ),
    )

    result = workspace_api.update_workspace_requirement_strategy(
        workspace_id,
        requirement_id,
        RequirementStrategyUpdate(target="compliance"),
        None,
    )

    assert result == updated
    assert calls["strategy"] == (
        workspace_id,
        requirement_id,
        "compliance",
    )
    assert calls["outline"] == (workspace_id, requirement_id)


def test_upload_creates_internal_workspace_without_project_step():
    service = FakeWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/workspaces",
        files={"file": ("招标文件.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "outline_ready"
    assert response.json()["document"]["validation_status"] == "valid"
    assert (
        response.json()["document"]["knowledge_scope"]
        == "organization_private"
    )
    assert response.cookies.get("bid_agent_session")


class InvalidWorkspaceService(FakeWorkspaceService):
    def create_from_upload(self, filename, content_type, content):
        raise InvalidTenderDocumentError(self.id, "不是有效招标文件。")


def test_invalid_document_is_rejected_without_internal_workspace_id():
    service = InvalidWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/workspaces",
        files={"file": ("普通材料.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TENDER_DOCUMENT"
    assert "workspace_id" not in response.json()["error"]["details"]


class PreparedWorkspaceService(FakeWorkspaceService):
    def __init__(self):
        super().__init__()
        self.completed = False

    def prepare_from_upload(self, filename, content_type, content):
        workspace = self.create_from_upload(
            filename,
            content_type,
            content,
        )
        workspace["status"] = "extracting"
        return workspace, uuid4(), uuid4()

    def complete_prepared_upload(self, workspace_id, document_id, run_id):
        self.completed = True


def test_upload_queues_long_running_extraction_without_running_it_inline():
    service = PreparedWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/workspaces",
        files={"file": ("招标文件.docx", b"docx", "application/docx")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "extracting"
    assert service.completed is False
    assert job_service.enqueued is not None
    assert job_service.enqueued[0] == service.id


def test_same_file_upload_creates_a_fresh_workspace_and_pipeline_each_time():
    class FreshRunService(PreparedWorkspaceService):
        def prepare_from_upload(self, filename, content_type, content):
            self.id = uuid4()
            return super().prepare_from_upload(
                filename,
                content_type,
                content,
            )

    class RecordingJobs(FakeJobService):
        def __init__(self):
            super().__init__()
            self.all_enqueued = []

        def enqueue(self, workspace_id, document_id, run_id):
            self.all_enqueued.append(
                (workspace_id, document_id, run_id)
            )
            return super().enqueue(workspace_id, document_id, run_id)

    service = FreshRunService()
    jobs = RecordingJobs()
    app.dependency_overrides[get_workspace_service] = lambda: service
    app.dependency_overrides[get_workspace_job_service] = lambda: jobs
    client = TestClient(app)
    upload = {
        "file": ("同一招标文件.docx", b"same-content", "application/docx")
    }

    first = client.post("/api/v1/workspaces", files=upload)
    second = client.post("/api/v1/workspaces", files=upload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(jobs.all_enqueued) == 2
    assert jobs.all_enqueued[0][0] != jobs.all_enqueued[1][0]
    assert jobs.all_enqueued[0][2] != jobs.all_enqueued[1][2]


def test_other_session_cannot_read_review_or_download_files():
    class DeniedAccess(FakeAccessService):
        def authorize(self, workspace_id, request):
            raise WorkspaceAccessDeniedError

    app.dependency_overrides[get_workspace_access_service] = (
        lambda: DeniedAccess()
    )
    client = TestClient(app)
    workspace_id = uuid4()

    assert client.get(
        f"/api/v1/workspaces/{workspace_id}"
    ).status_code == 404
    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/review"
    ).status_code == 404
    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/review/download"
    ).status_code == 404
    assert client.get(
        f"/api/v1/workspaces/{workspace_id}/exports/{uuid4()}/download"
    ).status_code == 404


class RetryWorkspaceService(PreparedWorkspaceService):
    def prepare_retry(self, workspace_id):
        workspace = self.create_from_upload(
            "招标文件.docx",
            "application/docx",
            b"docx",
        )
        workspace["id"] = workspace_id
        workspace["status"] = "extracting"
        return workspace, uuid4(), uuid4()


def test_failed_workspace_can_resume_saved_document_processing():
    service = RetryWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(f"/api/v1/workspaces/{service.id}/retry")

    assert response.status_code == 202
    assert response.json()["id"] == str(service.id)
    assert response.json()["status"] == "extracting"
    assert service.completed is False
    assert job_service.enqueued is not None
