from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.requirements import get_requirement_service
from app.main import app


NOW = datetime.now(UTC)


class FakeRequirementService:
    def __init__(self):
        self.project_id = uuid4()
        self.requirement_id = uuid4()
        self.document_id = uuid4()
        self.source_id = uuid4()
        self.item = {
            "id": self.requirement_id,
            "project_id": self.project_id,
            "type": "technical",
            "title": "系统备份",
            "normalized_text": "系统应支持数据备份。",
            "quote": "系统应支持数据备份。",
            "importance": "medium",
            "confidence": 0.8,
            "status": "pending",
            "sources": [
                {
                    "id": self.source_id,
                    "document_id": self.document_id,
                    "filename": "招标文件.pdf",
                    "locator": {
                        "kind": "page",
                        "page": 12,
                        "paragraph_start": None,
                        "paragraph_end": None,
                    },
                }
            ],
            "created_at": NOW,
            "updated_at": NOW,
        }

    def extract(self, project_id, document_ids):
        return 5, 1

    def list(self, project_id, **kwargs):
        return [self.item]

    def update(self, project_id, requirement_id, changes):
        return {**self.item, **changes}

    def reject(self, project_id, requirement_id):
        return None


def make_client():
    service = FakeRequirementService()
    app.dependency_overrides[get_requirement_service] = lambda: service
    return TestClient(app), service


def teardown_function():
    app.dependency_overrides.clear()


def test_extract_and_list_requirements():
    client, service = make_client()

    extracted = client.post(
        f"/api/v1/projects/{service.project_id}/requirements/extract",
        json={"document_ids": [str(service.document_id)]},
    )
    listing = client.get(
        f"/api/v1/projects/{service.project_id}/requirements"
    )

    assert extracted.status_code == 202
    assert extracted.json()["created_count"] == 5
    assert listing.status_code == 200
    assert listing.json()[0]["sources"][0]["locator"]["page"] == 12


def test_confirm_requirement():
    client, service = make_client()

    response = client.patch(
        f"/api/v1/projects/{service.project_id}/requirements/{service.requirement_id}",
        json={"status": "confirmed", "title": "已确认要求"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["title"] == "已确认要求"


def test_reject_requirement():
    client, service = make_client()

    response = client.delete(
        f"/api/v1/projects/{service.project_id}/requirements/{service.requirement_id}"
    )

    assert response.status_code == 204
