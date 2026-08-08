from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "deploy_ecs.sh"


def test_ecs_deploy_script_has_safety_and_recovery_gates():
    content = SCRIPT.read_text(encoding="utf-8")

    assert 'EXPECTED_DIR="${BID_AGENT_DIR:-/opt/bid-agent}"' in content
    assert 'DEPLOY_BRANCH="${BID_AGENT_BRANCH:-codex/v2-response-map}"' in content
    assert "git status --porcelain" in content
    assert "git pull --ff-only" in content
    assert "git switch --track -c" in content
    assert "pg_dump" in content
    assert "test -s" in content
    assert "chmod 600" in content
    assert "docker compose build backend worker frontend" in content
    assert "docker compose logs --tail=200 worker" in content
    assert "curl --fail" in content
    assert "http://127.0.0.1/api/v1/access/status" in content
    assert "代码回滚点" in content
    assert "rm -rf" not in content
    assert "git reset --hard" not in content
