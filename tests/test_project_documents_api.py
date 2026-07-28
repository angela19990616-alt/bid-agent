from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.project_documents import get_project_document_service
from app.main import app
from app.services.project_document_service import (
    DocumentParseFailedError,
    ProjectDocument,
)


NOW = datetime.now(UTC)


class FakeDocumentService:
    def __init__(self):
        self.project_id = uuid4()
        self.document = ProjectDocument(
            id=uuid4(),
            project_id=self.project_id,
            filename="招标文件.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            size_bytes=100,
            status="parsed",
            error_code=None,
            error_message=None,
            source_count=3,
            created_at=NOW,
            updated_at=NOW,
            job_id=uuid4(),
        )

    def upload_and_parse(self, project_id, filename, content_type, content):
        return ProjectDocument(
            **{
                **self.document.__dict__,
                "project_id": project_id,
                "filename": filename,
                "content_type": content_type,
                "size_bytes": len(content),
            }
        )

    def list(self, project_id):
        return [self.document]

    def get(self, project_id, document_id):
        return self.document

    def retry_parse(self, project_id, document_id):
        return self.document


def make_client(service=None):
    service = service or FakeDocumentService()
    app.dependency_overrides[get_project_document_service] = lambda: service
    return TestClient(app), service


def teardown_function():
    app.dependency_overrides.clear()


def test_upload_project_document_without_model_call():
    client, service = make_client()

    response = client.post(
        f"/api/v1/projects/{service.project_id}/documents",
        files={
            "file": (
                "招标文件.docx",
                b"document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "parsed"
    assert response.json()["source_count"] == 3


def test_list_project_documents():
    client, service = make_client()

    response = client.get(
        f"/api/v1/projects/{service.project_id}/documents"
    )

    assert response.status_code == 200
    assert response.json()[0]["id"] == str(service.document.id)


class FailedDocumentService(FakeDocumentService):
    def upload_and_parse(self, project_id, filename, content_type, content):
        raise DocumentParseFailedError(
            uuid4(),
            uuid4(),
            "DOCUMENT_EMPTY",
            "文件为空",
        )


def test_parse_failure_returns_retry_reference():
    client, service = make_client(FailedDocumentService())

    response = client.post(
        f"/api/v1/projects/{service.project_id}/documents",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "DOCUMENT_EMPTY"
    assert response.json()["error"]["details"]["retryable"] is True
