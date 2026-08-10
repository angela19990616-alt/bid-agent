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
    assert "proxy_read_timeout 300s" in CONFIG


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


def test_frontend_is_only_published_on_the_host_loopback():
    assert '"127.0.0.1:8080:80"' in COMPOSE
    assert '"80:80"' not in COMPOSE


def test_host_gateway_enforces_domain_tls_and_safe_limits():
    host_config = (
        Path(__file__).parents[1] / "deploy" / "nginx-bid.conf"
    ).read_text(encoding="utf-8")
    assert "server_name bid.angela-tech.com" in host_config
    assert "listen 80 default_server" in host_config
    assert "listen 443 ssl http2 default_server" in host_config
    assert "return 444" in host_config
    assert "client_max_body_size 25m" in host_config
    assert "proxy_read_timeout 300s" in host_config
    assert "zone=bid_invite" in host_config
    assert "Strict-Transport-Security" in host_config
    assert "/etc/nginx/proxy_params" not in host_config
    assert "ssl_protocols TLSv1.2 TLSv1.3" in host_config
    assert "options-ssl-nginx.conf" not in host_config


def test_host_gateway_allows_only_literal_ipv4_through_invite_gateway():
    host_config = (
        Path(__file__).parents[1] / "deploy" / "nginx-bid.conf"
    ).read_text(encoding="utf-8")
    raw_ip_server = host_config.split("server {", 2)[1]
    assert "$host !~" in raw_ip_server
    assert "[0-9]{1,3}" in raw_ip_server
    assert "location = /api/v1/access/invite" in raw_ip_server
    assert "location /api/" in raw_ip_server
    assert "proxy_pass http://127.0.0.1:8080" in raw_ip_server
    assert "proxy_read_timeout 300s" in raw_ip_server


def test_bootstrap_gateway_rejects_raw_ip_and_serves_acme_challenges():
    bootstrap = (
        Path(__file__).parents[1] / "deploy" / "nginx-bid-bootstrap.conf"
    ).read_text(encoding="utf-8")
    assert "listen 80 default_server" in bootstrap
    assert "return 444" in bootstrap
    assert "server_name bid.angela-tech.com" in bootstrap
    assert "/.well-known/acme-challenge/" in bootstrap
    assert "proxy_pass http://127.0.0.1:8080" in bootstrap
