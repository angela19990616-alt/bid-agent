from fastapi.testclient import TestClient

from app import main
from app.api import documents


client = TestClient(main.app)


def test_root():
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "AI标书Agent已经启动"
    assert payload["version"] == "0.1.0"


def test_health_when_dependencies_are_healthy(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_postgres",
        lambda: {"status": "healthy", "database": "bid_agent"},
    )
    monkeypatch.setattr(main, "check_redis", lambda: {"status": "healthy"})

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_when_a_dependency_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_postgres",
        lambda: {"status": "unhealthy", "error": "not available"},
    )
    monkeypatch.setattr(main, "check_redis", lambda: {"status": "healthy"})

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"


def test_upload_text_document(monkeypatch):
    monkeypatch.setattr(
        documents.IngestionService,
        "ingest",
        lambda self, **kwargs: (7, 2),
    )

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("案例.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 201
    assert response.json()["id"] == 7
    assert response.json()["chunk_count"] == 2
