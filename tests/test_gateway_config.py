from pathlib import Path


CONFIG = (
    Path(__file__).parents[1] / "frontend" / "nginx.conf"
).read_text(encoding="utf-8")
WORKER = (
    Path(__file__).parents[1] / "frontend" / "worker" / "index.ts"
).read_text(encoding="utf-8")


def test_gateway_uses_unique_backend_container_name():
    assert "proxy_pass http://bid-backend:8000" in CONFIG
    assert "proxy_pass http://backend:8000" not in CONFIG


def test_gateway_has_bounded_upload_proxy_timeouts():
    assert "client_max_body_size 25m" in CONFIG
    assert "proxy_connect_timeout 10s" in CONFIG
    assert "proxy_send_timeout 30s" in CONFIG
    assert "proxy_read_timeout 60s" in CONFIG


def test_sites_gateway_adds_private_edge_secret():
    assert "BID_AGENT_EDGE_SECRET" in WORKER
    assert 'headers.set("X-Bid-Agent-Edge-Secret"' in WORKER
