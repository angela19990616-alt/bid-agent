from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.workspaces import get_workspace_service
from app.main import app
from app.services.workspace_service import InvalidTenderDocumentError


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

    def get_latest(self):
        return self.get(self.id)


def teardown_function():
    app.dependency_overrides.clear()


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


class InvalidWorkspaceService(FakeWorkspaceService):
    def create_from_upload(self, filename, content_type, content):
        raise InvalidTenderDocumentError(self.id, "不是有效招标文件。")


def test_invalid_document_is_rejected_with_workspace_reference():
    service = InvalidWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/workspaces",
        files={"file": ("普通材料.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TENDER_DOCUMENT"
    assert response.json()["error"]["details"]["workspace_id"] == str(
        service.id
    )


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


def test_upload_schedules_long_running_extraction_after_response():
    service = PreparedWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.post(
        "/api/v1/workspaces",
        files={"file": ("招标文件.docx", b"docx", "application/docx")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "extracting"
    assert service.completed is True


def test_latest_workspace_can_be_recovered_without_exposing_internal_id():
    service = FakeWorkspaceService()
    app.dependency_overrides[get_workspace_service] = lambda: service
    client = TestClient(app)

    response = client.get("/api/v1/workspaces/recent/latest")

    assert response.status_code == 200
    assert response.json()["status"] == "outline_ready"


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
    assert service.completed is True
