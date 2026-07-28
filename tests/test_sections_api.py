from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.sections import get_section_service
from app.main import app


NOW = datetime.now(UTC)


class FakeSectionService:
    def __init__(self):
        self.project_id = uuid4()
        self.section_id = uuid4()
        self.requirement_id = uuid4()
        self.version_id = uuid4()

    def _item(self, status="generated"):
        return {
            "id": self.section_id,
            "project_id": self.project_id,
            "title": "实施方案",
            "status": status,
            "requirement_ids": [self.requirement_id],
            "current_version": {
                "id": self.version_id,
                "version_no": 1,
                "content": "章节正文",
                "origin": "generated",
                "created_at": NOW,
            },
            "findings": [],
            "created_at": NOW,
            "updated_at": NOW,
        }

    def create(self, project_id, title, requirement_ids):
        return self._item("drafting")

    def generate(self, project_id, section_id):
        return self._item()

    def get(self, project_id, section_id):
        return self._item()

    def save_content(
        self,
        project_id,
        section_id,
        base_version_id,
        content,
    ):
        item = self._item("edited")
        item["current_version"]["content"] = content
        item["current_version"]["origin"] = "edited"
        return item

    def approve(self, project_id, section_id):
        return self._item("approved")


def make_client():
    service = FakeSectionService()
    app.dependency_overrides[get_section_service] = lambda: service
    return TestClient(app), service


def teardown_function():
    app.dependency_overrides.clear()


def test_section_create_generate_edit_and_approve():
    client, service = make_client()
    base = f"/api/v1/projects/{service.project_id}/sections"

    created = client.post(
        base,
        json={
            "title": "实施方案",
            "requirement_ids": [str(service.requirement_id)],
        },
    )
    generated = client.post(f"{base}/{service.section_id}/generate")
    edited = client.put(
        f"{base}/{service.section_id}/content",
        json={
            "base_version_id": str(service.version_id),
            "content": "人工编辑后的章节正文",
        },
    )
    approved = client.post(f"{base}/{service.section_id}/approve")

    assert created.status_code == 201
    assert generated.status_code == 202
    assert edited.json()["current_version"]["origin"] == "edited"
    assert approved.json()["status"] == "approved"
