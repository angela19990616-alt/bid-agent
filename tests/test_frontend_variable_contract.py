from pathlib import Path
from typing import get_args

from app.models.generation_profiles import TemplateVariableDecisionResponse


def test_frontend_declares_every_backend_variable_resolution_state():
    frontend = (
        Path(__file__).resolve().parents[1] / "frontend" / "app" / "page.tsx"
    ).read_text(encoding="utf-8")
    annotation = TemplateVariableDecisionResponse.model_fields[
        "resolution_state"
    ].annotation

    for state in get_args(annotation):
        assert f'"{state}"' in frontend


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
