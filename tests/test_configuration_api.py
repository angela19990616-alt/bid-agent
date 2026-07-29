from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.configuration import get_knowledge_engine
from app.main import app


class FakeKnowledgeEngine:
    def __init__(self):
        self.imported = None

    def list_summaries(self):
        return [
            {
                "id": uuid4(),
                "category": "historical_bid",
                "title": "历史响应文件",
                "metadata": {"public_training": False},
                "permission_scope": "organization_private",
                "version": 1,
                "checksum": "a" * 64,
                "text_chars": 1200,
            }
        ]

    def import_document(self, filename, content, *, source_role):
        self.imported = (filename, content, source_role)
        return {
            "id": uuid4(),
            "category": "historical_bid",
            "title": "历史响应文件",
            "metadata": {
                "public_training": False,
                "verified_enterprise_fact": False,
            },
            "permission_scope": "organization_private",
            "status": "active",
            "version": 1,
            "checksum": "b" * 64,
            "text_chars": 1200,
            "segment_count": 20,
            "import_status": "created",
        }


def teardown_function():
    app.dependency_overrides.clear()


def test_knowledge_list_does_not_expose_private_content():
    engine = FakeKnowledgeEngine()
    app.dependency_overrides[get_knowledge_engine] = lambda: engine

    response = TestClient(app).get("/api/v1/configuration/knowledge")

    assert response.status_code == 200
    assert "content" not in response.json()[0]
    assert response.json()[0]["text_chars"] == 1200


def test_historical_docx_import_is_private_and_fact_unverified():
    engine = FakeKnowledgeEngine()
    app.dependency_overrides[get_knowledge_engine] = lambda: engine

    response = TestClient(app).post(
        "/api/v1/configuration/knowledge/documents",
        data={"source_role": "response_content"},
        files={
            "file": (
                "历史响应.docx",
                b"PK-private-content",
                (
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
            )
        },
    )

    assert response.status_code == 201
    assert response.json()["permission_scope"] == "organization_private"
    assert response.json()["metadata"]["public_training"] is False
    assert (
        response.json()["metadata"]["verified_enterprise_fact"] is False
    )
    assert engine.imported[2] == "response_content"
