from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.api.projects import get_project_service
from app.main import app
from app.services.project_service import Project, ProjectNotFoundError


NOW = datetime.now(UTC)


class FakeProjectService:
    def __init__(self):
        self.project = Project(
            id=uuid4(),
            name="测试项目",
            status="draft",
            created_at=NOW,
            updated_at=NOW,
        )

    def create(self, name: str) -> Project:
        return Project(
            id=self.project.id,
            name=name,
            status="draft",
            created_at=NOW,
            updated_at=NOW,
        )

    def list(self) -> list[Project]:
        return [self.project]

    def get(self, project_id: UUID) -> Project:
        if project_id != self.project.id:
            raise ProjectNotFoundError(str(project_id))
        return Project(
            **{
                **self.project.__dict__,
                "document_count": 2,
                "requirement_count": 0,
                "section_count": 0,
            }
        )


def make_client():
    service = FakeProjectService()
    app.dependency_overrides[get_project_service] = lambda: service
    return TestClient(app), service


def teardown_function():
    app.dependency_overrides.clear()


def test_create_and_list_projects():
    client, service = make_client()

    created = client.post(
        "/api/v1/projects",
        json={"name": "  新项目  "},
    )
    listing = client.get("/api/v1/projects")

    assert created.status_code == 201
    assert created.json()["name"] == "新项目"
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == str(service.project.id)


def test_get_project_detail():
    client, service = make_client()

    response = client.get(f"/api/v1/projects/{service.project.id}")

    assert response.status_code == 200
    assert response.json()["document_count"] == 2


def test_project_not_found_uses_safe_error_shape():
    client, _ = make_client()

    response = client.get(f"/api/v1/projects/{uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    assert "request_id" in response.json()["error"]


def test_blank_project_name_is_rejected():
    client, _ = make_client()

    response = client.post("/api/v1/projects", json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "X-Request-ID" in response.headers
