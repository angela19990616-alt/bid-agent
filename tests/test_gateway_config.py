from pathlib import Path


CONFIG = (
    Path(__file__).parents[1] / "frontend" / "nginx.conf"
).read_text(encoding="utf-8")
WORKER = (
    Path(__file__).parents[1] / "frontend" / "worker" / "index.ts"
).read_text(encoding="utf-8")
DOCKERFILE = (
    Path(__file__).parents[1] / "frontend" / "Dockerfile"
).read_text(encoding="utf-8")
COMPOSE = (
    Path(__file__).parents[1] / "docker-compose.yml"
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


def test_ecs_gateway_adds_private_edge_secret_without_baking_it_in():
    assert (
        "proxy_set_header X-Bid-Agent-Edge-Secret "
        "${BID_AGENT_EDGE_SECRET};"
    ) in CONFIG
    assert "/etc/nginx/templates/default.conf.template" in DOCKERFILE
    assert "NGINX_ENVSUBST_FILTER: BID_AGENT_EDGE_SECRET" in COMPOSE


def test_ecs_gateway_rate_limits_reads_and_paid_writes_per_ip():
    assert "zone=bid_api_per_ip" in CONFIG
    assert "zone=bid_writes_per_ip" in CONFIG
    assert "limit_req_status 429" in CONFIG
