from pathlib import Path


def test_frontend_uses_backend_presentation_without_copying_state_enum():
    frontend = (
        Path(__file__).resolve().parents[1] / "frontend" / "app" / "page.tsx"
    ).read_text(encoding="utf-8")

    assert "resolution_state: string" in frontend
    assert "variableResolutionLabel" in frontend
    assert "variableNextAction" in frontend
    assert "item.resolution_label?.trim()" in frontend
    assert "item.next_action?.trim()" in frontend
    assert "fillStatusLabels" not in frontend


def test_frontend_consumes_backend_review_group_contract():
    frontend = (
        Path(__file__).resolve().parents[1] / "frontend" / "app" / "page.tsx"
    ).read_text(encoding="utf-8")

    for field in (
        "semantics_recognized",
        "resolution_state",
        "resolution_label",
        "next_action",
        "review_group_key",
        "review_group_label",
    ):
        assert field in frontend
    assert "templateVariableGroups" in frontend
    assert "同一对象的不同属性横向展示" in frontend


def test_release_guard_runs_frontend_tests_not_build_only():
    root = Path(__file__).resolve().parents[1]
    release_guard = (root / "scripts" / "verify_release.sh").read_text(
        encoding="utf-8"
    )
    agent_rules = (root / "AGENTS.md").read_text(encoding="utf-8")

    assert "npm --prefix frontend test" in release_guard
    assert "前后端契约" in agent_rules
    assert "后端响应模型" in agent_rules
