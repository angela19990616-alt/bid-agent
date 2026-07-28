from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.exports import get_export_service
from app.main import app


NOW = datetime.now(UTC)


class FakeExportService:
    def __init__(self, path):
        self.project_id = uuid4()
        self.section_id = uuid4()
        self.version_id = uuid4()
        self.export_id = uuid4()
        self.path = path

    def _item(self):
        return {
            "id": self.export_id,
            "project_id": self.project_id,
            "section_id": self.section_id,
            "section_version_id": self.version_id,
            "format": "docx",
            "status": "succeeded",
            "filename": "实施方案.docx",
            "error_code": None,
            "error_message": None,
            "created_at": NOW,
            "updated_at": NOW,
        }

    def create(self, project_id, section_id, section_version_id):
        return self._item()

    def get(self, project_id, export_id):
        return self._item()

    def download_info(self, project_id, export_id):
        return self.path, "实施方案.docx"


def test_create_and_download_export(tmp_path):
    file_path = tmp_path / "test.docx"
    file_path.write_bytes(b"docx")
    service = FakeExportService(file_path)
    app.dependency_overrides[get_export_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        f"/api/v1/projects/{service.project_id}/exports",
        json={
            "section_id": str(service.section_id),
            "section_version_id": str(service.version_id),
            "format": "docx",
        },
    )
    downloaded = client.get(
        f"/api/v1/projects/{service.project_id}/exports/{service.export_id}/download"
    )

    app.dependency_overrides.clear()
    assert created.status_code == 202
    assert created.json()["status"] == "succeeded"
    assert downloaded.status_code == 200
    assert downloaded.content == b"docx"
