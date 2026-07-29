import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "acceptance_mvp.py"
SPEC = importlib.util.spec_from_file_location("acceptance_mvp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_acceptance_report_omits_source_and_generated_text():
    workspace = {
        "id": "W1",
        "status": "outline_ready",
        "document": {"validation_status": "valid"},
        "technical_requirements": [
            {
                "type": "scoring",
                "target_chapter": "技术评分点响应",
                "sources": [{"locator": {"page": 8}}],
            }
        ],
        "compliance_reminder_count": 2,
        "outline": [
            {
                "id": "S1",
                "title": "技术评分点响应",
                "requirement_ids": ["R1"],
            }
        ],
    }

    summary = MODULE.summarize_workspace(workspace)

    assert summary["technical_requirement_count"] == 1
    assert summary["traceable_requirement_count"] == 1
    assert "sources" not in summary
    assert "content" not in summary


def test_generated_section_summary_only_exposes_counts():
    section = {
        "id": "S1",
        "title": "实施计划",
        "status": "generated",
        "current_version": {"content": "私密生成正文"},
        "findings": [
            {"severity": "blocking", "message": "私密校核详情"}
        ],
    }

    summary = MODULE.summarize_section(section)

    assert summary["content_chars"] == 6
    assert summary["blocking"] is True
    assert "content" not in summary
    assert "message" not in summary
