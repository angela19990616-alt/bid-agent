from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.internal_dashboard import get_usage_dashboard_service
from app.main import app


class FakeDashboard:
    def summary(self):
        return {
            "totals": {
                "projects": 12,
                "approved_sections": 34,
                "exports": 5,
                "calls": 78,
                "tokens": 123456,
                "job_success_rate": 92.5,
            },
            "models": [
                {
                    "model": "deepseek-v4-flash",
                    "task": "extraction",
                    "calls": 10,
                    "succeeded": 9,
                    "failed": 1,
                    "tokens": 30000,
                    "avg_seconds": 12.4,
                }
            ],
            "daily": [
                {
                    "day": date(2026, 8, 3),
                    "projects": 2,
                    "jobs_succeeded": 2,
                    "jobs_failed": 0,
                    "exports": 1,
                    "calls": 10,
                    "tokens": 30000,
                }
            ],
            "jobs": [{"status": "succeeded", "count": 11}],
        }


def test_internal_usage_dashboard_is_aggregate_and_unlinked():
    app.dependency_overrides[get_usage_dashboard_service] = FakeDashboard
    try:
        response = TestClient(app).get("/internal/usage")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert "Bid Agent 使用情况" in response.text
    assert "123,456" in response.text
    assert "deepseek-v4-flash" in response.text
    assert "UUID" not in response.text
    assert "文件名" not in response.text


def test_public_frontend_has_no_internal_dashboard_link():
    source = Path("frontend/app/page.tsx").read_text(encoding="utf-8")

    assert "/internal/usage" not in source


def test_internal_dashboard_is_loopback_only_and_not_proxied():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    nginx = Path("frontend/nginx.conf").read_text(encoding="utf-8")

    assert '"127.0.0.1:8000:8000"' in compose
    assert '"0.0.0.0:8000:8000"' not in compose
    assert "location /internal" not in nginx
