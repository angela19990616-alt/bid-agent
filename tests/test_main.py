from fastapi.testclient import TestClient
from types import SimpleNamespace

from app import main
from app.api import access, documents
from app.services import invite_access_service


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

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_when_a_dependency_is_unhealthy(monkeypatch):
    monkeypatch.setattr(
        main,
        "check_postgres",
        lambda: {"status": "unhealthy", "error": "not available"},
    )
    monkeypatch.setattr(main, "check_redis", lambda: {"status": "healthy"})

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "unhealthy"


def test_health_does_not_require_dependencies():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_production_api_rejects_direct_requests(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            app_env="production",
            edge_proxy_secret="edge-secret",
        ),
    )

    response = client.get("/api/v1/workspaces/example")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "AUTHORIZED_ENTRY_REQUIRED"


def test_production_api_accepts_authorized_gateway(monkeypatch):
    monkeypatch.setattr(
        main,
        "settings",
        SimpleNamespace(
            app_env="production",
            edge_proxy_secret="edge-secret",
        ),
    )

    response = client.get(
        "/api/v1/workspaces/example",
        headers={"X-Bid-Agent-Edge-Secret": "edge-secret"},
    )

    assert response.status_code != 403


def test_production_invite_gate_issues_http_only_access_cookie(monkeypatch):
    runtime = SimpleNamespace(
        app_env="production",
        edge_proxy_secret="edge-secret",
        invite_code="DAYUE-TEST",
        invite_access_ttl_hours=24,
    )
    monkeypatch.setattr(main, "settings", runtime)
    monkeypatch.setattr(access, "settings", runtime)
    monkeypatch.setattr(invite_access_service, "settings", runtime)
    headers = {"X-Bid-Agent-Edge-Secret": "edge-secret"}

    status_response = client.get(
        "/api/v1/access/status",
        headers=headers,
    )
    denied_response = client.get(
        "/api/v1/workspaces/example",
        headers=headers,
    )
    invalid_response = client.post(
        "/api/v1/access/invite",
        headers=headers,
        json={"code": "WRONG-CODE"},
    )
    authorized_response = client.post(
        "/api/v1/access/invite",
        headers=headers,
        json={"code": "DAYUE-TEST"},
    )
    allowed_response = client.get(
        "/api/v1/workspaces/example",
        headers=headers,
    )

    assert status_response.json() == {
        "required": True,
        "authorized": False,
    }
    assert denied_response.status_code == 401
    assert (
        denied_response.json()["error"]["code"]
        == "INVITE_ACCESS_REQUIRED"
    )
    assert invalid_response.status_code == 401
    assert authorized_response.status_code == 200
    cookie_header = authorized_response.headers["set-cookie"]
    assert "bid_agent_invite_access=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert allowed_response.status_code != 401


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
